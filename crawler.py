#!/usr/bin/env python3
"""Full Javtiful metadata crawler and database synchronizer."""

import argparse
import time
from urllib.parse import urljoin

from database import JsonDatabase
from javtiful_scraper import ProviderManager


BASE_URL = "https://javtiful.com"


class Crawler:
    def __init__(self, provider, db, delay=0.0, start_page=1, end_page=0):
        self.provider = provider
        self.db = db
        self.delay = max(0.0, delay)
        self.start_page = max(1, start_page)
        self.end_page = max(0, end_page)
        self.stats = {
            "pages": 0,
            "videos_seen": 0,
            "added": 0,
            "duplicates": 0,
            "skipped": 0,
            "errors": 0,
        }

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
            print(
                f"[{context}] {result['status']}: "
                f"{result.get('code', raw.get('code', '?'))}",
                flush=True,
            )
        except Exception as exc:
            self.stats["errors"] += 1
            print(
                f"[{context}] ERROR: {raw.get('post_url')}: {exc}",
                flush=True,
            )
        self.pause()

    def crawl_listing(self, url, label, start_page=1, end_page=0):
        """Crawl a listing between explicit page bounds.

        end_page=0 means continue until the site's pagination ends.
        """
        page = max(1, start_page)

        while True:
            if end_page and page > end_page:
                break

            print(f"[{label}] page {page}", flush=True)
            result = self.provider.scrape_listing(
                url,
                page=page,
                enrich=False,
            )
            self.stats["pages"] += 1

            items = result.get("items", [])
            for item in items:
                self.save_video(item, f"{label} p{page}")

            pagination = result.get("pagination", {})
            if not pagination.get("has_next") or not items:
                break

            page += 1
            self.pause()

    def crawl_directory(self, kind, start_page=1, end_page=0):
        directory = urljoin(
            BASE_URL,
            "/actresses" if kind == "actress" else "/channels",
        )
        page = max(1, start_page)
        seen = set()

        while True:
            if end_page and page > end_page:
                break

            print(f"[{kind}-directory] page {page}", flush=True)
            result = (
                self.provider.scrape_actresses(directory, page)
                if kind == "actress"
                else self.provider.scrape_studios(directory, page)
            )
            self.stats["pages"] += 1

            entries = result.get(
                "actresses" if kind == "actress" else "studios",
                [],
            )

            # A directory entry may appear on multiple pages. Keep the
            # directory range moving even when a page contains only entries
            # already discovered.
            new_entries = [
                x for x in entries
                if x.get("slug") and x["slug"] not in seen
            ]

            for entry in new_entries:
                seen.add(entry["slug"])

            for entry in new_entries:
                videos_url = entry.get("url")

                if not videos_url:
                    if kind == "actress":
                        videos_url = urljoin(
                            BASE_URL + "/",
                            f"actress/{entry['slug']}",
                        )
                    else:
                        videos_url = urljoin(
                            BASE_URL + "/",
                            f"channel/{entry['slug']}",
                        )

                # IMPORTANT: the directory range controls which actresses/
                # studios are discovered. Once discovered, crawl ALL of that
                # entity's video pages unless the site's pagination ends.
                self.crawl_listing(
                    videos_url,
                    f"{kind}:{entry['slug']}",
                    start_page=1,
                    end_page=0,
                )

            pagination = result.get("pagination", {})
            if not pagination.get("has_next") or not entries:
                break

            page += 1
            self.pause()

    def run(self, scope="all"):
        if scope in ("all", "main"):
            self.crawl_listing(
                urljoin(BASE_URL, "/main"),
                "main",
                start_page=self.start_page,
                end_page=self.end_page,
            )

        if scope in ("all", "actresses"):
            self.crawl_directory(
                "actress",
                start_page=self.start_page,
                end_page=self.end_page,
            )

        if scope in ("all", "studios"):
            self.crawl_directory(
                "studio",
                start_page=self.start_page,
                end_page=self.end_page,
            )

        self.db.finalize(self.stats)
        print("\nCrawl complete:", self.stats, flush=True)
        return self.stats


def main():
    parser = argparse.ArgumentParser(
        description="Crawl Javtiful into grouped JSON database"
    )
    parser.add_argument(
        "--scope",
        choices=("all", "main", "actresses", "studios"),
        default="all",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Seconds between video requests",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="First directory/listing page to process",
    )
    parser.add_argument(
        "--end-page",
        type=int,
        default=0,
        help="Last directory/listing page to process (0 = until pagination ends)",
    )
    # Keep the old option for compatibility with existing manual runs.
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Deprecated compatibility option; use --start-page/--end-page",
    )
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--database", default="database")
    args = parser.parse_args()

    start_page = max(1, args.start_page)
    end_page = max(0, args.end_page)

    if args.max_pages is not None and args.end_page == 0:
        end_page = start_page + args.max_pages - 1 if args.max_pages > 0 else 0

    if end_page and end_page < start_page:
        parser.error("--end-page must be greater than or equal to --start-page")

    manager = ProviderManager()
    provider = manager.resolve(BASE_URL)
    provider.timeout = args.timeout
    provider.retries = args.retries

    crawler = Crawler(
        provider,
        JsonDatabase(args.database),
        delay=args.delay,
        start_page=start_page,
        end_page=end_page,
    )
    crawler.run(args.scope)


if __name__ == "__main__":
    raise SystemExit(main())
