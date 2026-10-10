"""Resumable runner for a manifest of media you own or are authorized to redistribute.

Manifest format:
{
  "items": [
    {
      "id": "stable-id",
      "url": "https://example.com/media.mp4",
      "title": "Example title",
      "thumbnail": "https://example.com/thumb.jpg",
      "duration": 123,
      "source_url": "https://example.com/page"
    }
  ]
}

This runner intentionally consumes a supplied manifest. It does not crawl or
extract items from any particular website.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.downloader.downloader import Downloader
from app.jobs.checkpoint_store import CheckpointStore
from app.models.video import Video
from app.uploaders.telegram import TelegramUploader

LOG = logging.getLogger("resumable_manifest_runner")
ROOT = Path(__file__).resolve().parents[2]


def load_manifest(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError(f"Manifest must be an object with an 'items' array: {path}")

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(payload["items"]):
        if not isinstance(raw, dict):
            raise ValueError(f"Manifest item #{index + 1} must be an object")
        item_id = str(raw.get("id", "")).strip()
        url = str(raw.get("url", "")).strip()
        parsed = urlparse(url)
        if not item_id:
            raise ValueError(f"Manifest item #{index + 1} is missing a stable 'id'")
        if item_id in seen:
            raise ValueError(f"Duplicate manifest item id: {item_id}")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Item {item_id!r} must have a valid HTTP(S) media URL")
        seen.add(item_id)
        items.append({**raw, "id": item_id, "url": url})
    return items


def persist_checkpoint(path: Path) -> None:
    """Commit/push the JSON checkpoint after each item when enabled by CI."""
    if os.getenv("CHECKPOINT_GIT_PUSH", "0").strip() != "1":
        return
    branch = os.getenv("GITHUB_REF_NAME", "").strip()
    if not branch:
        raise RuntimeError("GITHUB_REF_NAME is required for checkpoint pushes")
    relative_path = path.relative_to(ROOT).as_posix()
    subprocess.run(["git", "add", "--", relative_path], cwd=ROOT, check=True)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
        check=False,
    )
    if staged.returncode == 0:
        return
    if staged.returncode != 1:
        raise RuntimeError("Unable to inspect staged checkpoint changes")
    summary = CheckpointStore(path).summary()
    message = (
        "chore(checkpoint): save resumable job progress "
        f"({summary['completed']} completed, {summary['failed']} failed)"
    )
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=ROOT, check=True)
    subprocess.run(
        ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(["git", "commit", "-m", message], cwd=ROOT, check=True)
    subprocess.run(["git", "push", "origin", f"HEAD:{branch}"], cwd=ROOT, check=True)


def _message_ids(results: Any) -> list[str]:
    if not isinstance(results, list):
        results = [results]
    return [
        str(getattr(result, "id"))
        for result in results
        if getattr(result, "id", None) is not None
    ]


def run(manifest_path: Path, checkpoint_path: Path) -> int:
    items = load_manifest(manifest_path)
    store = CheckpointStore(checkpoint_path)
    destination = os.getenv("TELEGRAM_POST_CHANNEL_ID", "").strip()
    if not destination:
        raise RuntimeError("Set TELEGRAM_POST_CHANNEL_ID to your destination channel ID or @username")

    max_attempts = max(1, int(os.getenv("MAX_ITEM_ATTEMPTS", "5")))
    uploader = TelegramUploader()
    failures = 0
    try:
        for item in items:
            item_id = item["id"]
            title = str(item.get("title") or item_id)
            previous = store.get(item_id) or {}
            if previous.get("status") == "completed":
                LOG.info("SKIP completed item id=%s title=%r", item_id, title)
                continue
            if int(previous.get("attempts", 0)) >= max_attempts:
                LOG.warning("SKIP item id=%s: reached MAX_ITEM_ATTEMPTS=%s", item_id, max_attempts)
                failures += 1
                continue

            store.mark_processing(item_id, title=title, extra={"source_url": item.get("source_url", "")})
            with tempfile.TemporaryDirectory(prefix="media-job-") as temp_dir:
                try:
                    video = Video(
                        source_url=str(item.get("source_url") or item["url"]),
                        title=title,
                        thumbnail=item.get("thumbnail"),
                        duration=float(item["duration"]) if item.get("duration") is not None else None,
                        qualities={"source": item["url"]},
                    )
                    downloader = Downloader(workdir=Path(temp_dir) / "downloads")
                    downloader.download(video, "best")
                    if not video.local_path or not Path(video.local_path).is_file():
                        raise RuntimeError("Downloader did not produce a media file")
                    results = uploader.upload(
                        video.local_path,
                        chat_id=destination,
                        caption=title,
                        thumbnail=video.thumbnail,
                        duration=video.duration,
                        referer=video.source_url,
                    )
                    ids = _message_ids(results)
                    if not ids:
                        raise RuntimeError("Telegram uploader returned no message IDs")
                except Exception as exc:
                    failures += 1
                    store.mark_failed(item_id, f"{type(exc).__name__}: {exc}", title=title)
                    LOG.exception("FAILED item id=%s title=%r", item_id, title)
                    # Persist failure immediately so retries are bounded across runs.
                    persist_checkpoint(checkpoint_path)
                    continue

            # Keep this outside the processing try/except: if Git push fails after a
            # successful upload, do not incorrectly overwrite completed with failed.
            store.mark_completed(
                item_id,
                title=title,
                destination_message_id=ids[0],
                extra={"telegram_message_ids": ids, "source_url": item.get("source_url", "")},
            )
            persist_checkpoint(checkpoint_path)
            LOG.info("COMPLETED item id=%s title=%r telegram_messages=%s", item_id, title, ids)

    finally:
        for client in getattr(uploader, "_clients", []):
            try:
                if client.is_connected:
                    client.stop()
            except Exception:
                LOG.exception("Error stopping Telegram upload client")

    LOG.info("Run summary: %s", store.summary())
    return 1 if failures else 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="database/authorized_media.json")
    parser.add_argument("--checkpoint", default="database/processed.json")
    args = parser.parse_args()
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    manifest_path = (ROOT / args.manifest).resolve()
    checkpoint_path = (ROOT / args.checkpoint).resolve()
    try:
        return run(manifest_path, checkpoint_path)
    except Exception:
        LOG.exception("Resumable runner failed")
        return 2


if __name__ == "__main__":
    sys.exit(main())
