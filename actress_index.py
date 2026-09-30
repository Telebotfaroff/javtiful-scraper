#!/usr/bin/env python3
"""Build and refresh the persistent actress crawl queue."""

import argparse
import json
import os
import tempfile
import time

from javtiful_scraper import ProviderManager

BASE_URL = "https://javtiful.com"
INDEX_PATH = "database/index/indexactress.json"


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            value = json.load(fh)
        return value if isinstance(value, dict) else default
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_json(path, data):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".json-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def refresh_index(provider, index_path):
    data = load_json(index_path, {"total": 0, "actresses": {}})
    actresses = data.setdefault("actresses", {})
    page = 1

    while True:
        print(f"[actress-index] directory page {page}", flush=True)
        result = provider.scrape_actresses(f"{BASE_URL}/actresses", page=page)
        entries = result.get("actresses", [])

        for entry in entries:
            slug = str(entry.get("slug") or "").strip().lower()
            if not slug:
                continue
            existing = actresses.get(slug, {})
            profile_url = entry.get("url") or f"{BASE_URL}/actress/{slug}"
            profile = provider.scrape_listing(profile_url, page=1, enrich=False)
            pagination = profile.get("pagination") or {}
            total_pages = max(1, int(pagination.get("total_pages") or 1))
            last_page = max(0, int(existing.get("last_crawled_page") or 0))
            status = existing.get("status") or "pending"
            if last_page >= total_pages:
                status = "completed"

            actresses[slug] = {
                "name": entry.get("name") or existing.get("name") or slug,
                "slug": slug,
                "url": profile_url,
                "thumbnail": entry.get("thumbnail") or existing.get("thumbnail"),
                "total_videos": (entry.get("video_count") if entry.get("video_count") is not None else existing.get("total_videos", 0)),
                "total_pages": total_pages,
                "status": status,
                "last_crawled_page": last_page,
                "videos_crawled": int(existing.get("videos_crawled") or 0),
                "last_crawled_at": existing.get("last_crawled_at"),
            }
            print(f"[actress-index] {slug}: videos={actresses[slug]['total_videos']} pages={total_pages} status={status}", flush=True)

        pagination = result.get("pagination") or {}
        if not entries or not pagination.get("has_next"):
            break
        page += 1

    data["total"] = len(actresses)
    data["updated_at"] = int(time.time())
    write_json(index_path, data)
    print(f"[actress-index] complete | actresses={len(actresses)}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Refresh the actress index and crawl queue")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--index", default=INDEX_PATH)
    args = parser.parse_args()

    manager = ProviderManager()
    provider = manager.resolve(BASE_URL)
    provider.timeout = max(1, args.timeout)
    provider.retries = max(0, args.retries)
    refresh_index(provider, args.index)


if __name__ == "__main__":
    raise SystemExit(main())
