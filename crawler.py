#!/usr/bin/env python3
"""Full Javtiful metadata crawler and database synchronizer."""

import argparse
import time
from urllib.parse import urljoin

from database import JsonDatabase
from javtiful_scraper import ProviderManager


BASE_URL = "https://javtiful.com"


class Crawler:
    def __init__(self, provider, db, delay=0.0, max_pages=0):
        self.provider = provider
        self.db = db
        self.delay = max(0.0, delay)
        self.max_pages = max_pages
        self.stats = {"pages": 0, "videos_seen": 0, "added": 0, "duplicates": 0, "skipped": 0, "errors": 0}

    def pause(self):
        if self.delay:
            time.sleep(self.delay)

    def save_video(self, raw, context):
        self.stats["videos_seen"] += 1
        try:
            # Listing cards do not contain all post metadata, so enrich before persistence.
            details = self.provider.enrich_post(raw["post_url"])
            merged = dict(raw)
            merged.update(details)
            result = self.db.add_video(merged)
            if result["status"] == "added":
                self.stats["added"] += 1
            elif result["status"] == "duplicate":
                self.stats["duplicates"] += 1
            else:
                self.stats["skipped"] += 1
            print(f"[{context}] {result['status']}: {result.get('code', raw.get('code', '?'))}", flush=True)
        except Exception as exc:
            self.stats["errors"] += 1
            print(f"[{context}] ERROR: {raw.get('post_url')}: {exc}", flush=True)
        self.pause()

    def crawl_listing(self, url, label):
        page = 1
        while True:
            if self.max_pages and page > self.max_pages:
                break
            print(f"[{label}] page {page}", flush=True)
            result = self.provider.scrape_listing(url, page=page, enrich=False)
            self.stats["pages"] += 1
            items = result.get("items", [])
            for item in items:
                self.save_video(item, f"{label} p{page}")
            pagination = result.get("pagination", {})
            if not pagination.get("has_next") or not items:
                break
            page += 1
            self.pause()

    def crawl_directory(self, kind):
        directory = urljoin(BASE_URL, "/actresses" if kind == "actress" else "/channels")
        page = 1
        seen = set()
        while True:
            if self.max_pages and page > self.max_pages:
                break
            print(f"[{kind}-directory] page {page}", flush=True)
            result = (self.provider.scrape_actresses(directory, page) if kind == "actress"
                      else self.provider.scrape_studios(directory, page))
            self.stats["pages"] += 1
            entries = result.get("actresses" if kind == "actress" else "studios", [])
            new_entries = [x for x in entries if x.get("slug") and x["slug"] not in seen]
            for entry in new_entries:
                seen.add(entry["slug"])
            for entry in new_entries:
                videos_url = entry.get("url") or urljoin(directory + "/", f"{kind}/{entry['slug']}")
                # Javtiful uses /channel/ for studios.
                if kind == "studio":
                    videos_url = entry.get("url") or urljoin(BASE_URL + "/", f"channel/{entry['slug']}")
                self.crawl_listing(videos_url, f"{kind}:{entry['slug']}")
            if not result.get("pagination", {}).get("has_next") or not new_entries:
                break
            page += 1
            self.pause()

    def run(self, scope="all"):
        if scope in ("all", "main"):
            self.crawl_listing(urljoin(BASE_URL, "/main"), "main")
        if scope in ("all", "actresses"):
            self.crawl_directory("actress")
        if scope in ("all", "studios"):
            self.crawl_directory("studio")
        self.db.finalize(self.stats)
        print("\nCrawl complete:", self.stats, flush=True)
        return self.stats


def main():
    parser = argparse.ArgumentParser(description="Crawl Javtiful into grouped JSON database")
    parser.add_argument("--scope", choices=("all", "main", "actresses", "studios"), default="all")
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds between video requests")
    parser.add_argument("--max-pages", type=int, default=0, help="Maximum pages per listing/directory (0 = unlimited)")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--database", default="database")
    args = parser.parse_args()

    manager = ProviderManager()
    provider = manager.resolve(BASE_URL)
    provider.timeout = args.timeout
    provider.retries = args.retries
    crawler = Crawler(provider, JsonDatabase(args.database), delay=args.delay, max_pages=args.max_pages)
    crawler.run(args.scope)


if __name__ == "__main__":
    raise SystemExit(main())
