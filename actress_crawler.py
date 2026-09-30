#!/usr/bin/env python3
"""Crawl actresses from the persistent actress queue."""

import argparse
import json
import os
import tempfile
import time

from database import JsonDatabase
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


def save_progress(index_path, data):
    data["total"] = len(data.get("actresses", {}))
    write_json(index_path, data)


def select_actresses(data, requested_slug, limit):
    actresses = data.get("actresses", {})
    if requested_slug:
        slug = requested_slug.strip().lower()
        if slug not in actresses:
            raise ValueError(f"Actress not found in index: {slug}")
        return [(slug, actresses[slug])]

    selected = []
    for status in ("pending", "failed", "in_progress"):
        for slug, entry in actresses.items():
            if entry.get("status") == status:
                selected.append((slug, entry))
                if len(selected) >= limit:
                    return selected
    return selected


def crawl_actress(provider, db, index_path, data, slug, entry, delay, retries):
    total_pages = max(1, int(entry.get("total_pages") or 1))
    last_page = max(0, int(entry.get("last_crawled_page") or 0))

    if last_page >= total_pages:
        entry["status"] = "completed"
        entry["last_crawled_page"] = total_pages
        entry["last_crawled_at"] = int(time.time())
        save_progress(index_path, data)
        return

    entry["status"] = "in_progress"
    save_progress(index_path, data)
    url = entry.get("url") or f"{BASE_URL}/actress/{slug}"

    try:
        for page in range(last_page + 1, total_pages + 1):
            print(f"[actress:{slug}] page {page}/{total_pages}", flush=True)
            result = provider.scrape_listing(url, page=page, enrich=False)
            items = result.get("items") or []
            if not items:
                raise RuntimeError(f"Page {page} returned no items before indexed boundary {total_pages}")

            added = duplicates = errors = 0
            for item in items:
                post_url = item.get("post_url")
                if not post_url:
                    continue
                try:
                    details = provider.enrich_post(post_url)
                    merged = dict(item)
                    merged.update(details)
                    saved = db.add_video(merged)
                    if saved["status"] == "added":
                        added += 1
                    elif saved["status"] == "duplicate":
                        duplicates += 1
                except Exception as exc:
                    errors += 1
                    print(f"[actress:{slug} p{page}] ERROR {post_url}: {exc}", flush=True)
                    if errors > retries:
                        raise
                if delay:
                    time.sleep(delay)

            entry["last_crawled_page"] = page
            entry["videos_crawled"] = int(entry.get("videos_crawled") or 0) + added
            entry["last_crawled_at"] = int(time.time())
            entry["status"] = "completed" if page >= total_pages else "in_progress"
            save_progress(index_path, data)
            print(f"[actress:{slug}] page {page} complete | items={len(items)} added={added} duplicates={duplicates} errors={errors}", flush=True)

    except Exception:
        entry["status"] = "failed"
        entry["last_crawled_at"] = int(time.time())
        save_progress(index_path, data)
        raise


def main():
    parser = argparse.ArgumentParser(description="Crawl pending actresses from the actress index")
    parser.add_argument("--actress", default="")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--index", default=INDEX_PATH)
    parser.add_argument("--database", default="database")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be at least 1")

    data = load_json(args.index, {"total": 0, "actresses": {}})
    selected = select_actresses(data, args.actress, args.limit)
    if not selected:
        print("[actress-crawler] no pending or failed actresses", flush=True)
        return 0

    manager = ProviderManager()
    provider = manager.resolve(BASE_URL)
    provider.timeout = max(1, args.timeout)
    provider.retries = max(0, args.retries)
    db = JsonDatabase(args.database)

    for slug, entry in selected:
        crawl_actress(provider, db, args.index, data, slug, entry, max(0.0, args.delay), max(0, args.retries))

    # Reload the checkpointed index so finalize() cannot overwrite the
    # page/status progress with JsonDatabase's older in-memory copy.
    db.index_actress = load_json(args.index, {"total": 0, "actresses": {}})
    db.finalize({"source": "actress", "actresses_processed": len(selected)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
