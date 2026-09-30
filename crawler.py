#!/usr/bin/env python3
"""Full Javtiful metadata crawler and database synchronizer."""

import argparse
import json
import re
import time
from urllib.parse import urljoin, urlparse

from database import JsonDatabase
from javtiful_scraper import ProviderManager


BASE_URL = "https://javtiful.com"


class Crawler:
    def __init__(self, provider, db, delay=0.0, start_page=1, end_page=0, state_path=None, resume=False, retries=2):
        self.provider = provider
        self.db = db
        self.delay = max(0.0, delay)
        self.start_page = max(1, start_page)
        self.end_page = max(0, end_page)
        self.state_path = state_path
        self.resume = resume
        self.retries = max(0, retries)
        self.state = self._load_state() if self.resume else {}
        self.failed_items = []
        self.stats = {
            "pages": 0,
            "videos_seen": 0,
            "added": 0,
            "duplicates": 0,
            "skipped": 0,
            "errors": 0,
        }

    def _load_state(self):
        if not self.state_path:
            return {}
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                value = json.load(fh)
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save_state(self):
        if not self.state_path:
            return
        import os
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        temp = self.state_path + ".tmp"
        with open(temp, "w", encoding="utf-8") as fh:
            json.dump(self.state, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(temp, self.state_path)

    def _state_key(self, label, url):
        return f"{label}|{url.rstrip('/').lower()}"

    def _checkpoint(self, label, url, page):
        if not self.state_path:
            return
        key = self._state_key(label, url)
        self.state[key] = {"label": label, "url": url, "last_completed_page": page, "updated_at": int(time.time())}
        self._save_state()

    def _clear_checkpoint(self, label, url):
        if not self.state_path:
            return
        self.state.pop(self._state_key(label, url), None)
        self._save_state()

    def pause(self):
        if self.delay:
            time.sleep(self.delay)

    def save_video(self, raw, context, retry_count=0):
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
            if retry_count < self.retries:
                print(f"[{context}] retry {retry_count + 1}/{self.retries}: {raw.get('post_url')}", flush=True)
                self.pause()
                return self.save_video(raw, context, retry_count + 1)
            self.stats["errors"] += 1
            self.failed_items.append({"post_url": raw.get("post_url"), "context": context, "error": str(exc)})
            print(
                f"[{context}] ERROR: {raw.get('post_url')}: {exc}",
                flush=True,
            )
        self.pause()

    def crawl_listing(self, url, label, start_page=1, end_page=0):
        """Crawl a listing with explicit bounds and duplicate-page protection."""
        page = max(1, start_page)
        seen_posts = set()
        if self.resume:
            checkpoint = self.state.get(self._state_key(label, url), {})
            page = max(page, int(checkpoint.get("last_completed_page", 0)) + 1)

        while True:
            if end_page and page > end_page:
                break

            print(f"[{label}] page {page}", flush=True)
            result = self.provider.scrape_listing(url, page=page, enrich=False)
            self.stats["pages"] += 1
            items = result.get("items", [])

            page_urls = [item.get("post_url") for item in items if item.get("post_url")]
            checkpoint = self.state.get(self._state_key(label, url), {}) if self.resume else {}
            previous_page_urls = checkpoint.get("last_page_urls", [])
            if previous_page_urls and page_urls and page_urls == previous_page_urls:
                print(
                    f"[{label}] page {page} repeats the checkpointed last page; "
                    "stopping pagination.",
                    flush=True,
                )
                self._clear_checkpoint(label, url)
                break

            new_items = [
                item for item in items
                if item.get("post_url") and item["post_url"] not in seen_posts
            ]

            # Some sites return the last valid page for out-of-range pages.
            if items and not new_items:
                print(
                    f"[{label}] page {page} contains only previously seen posts; "
                    "stopping pagination.",
                    flush=True,
                )
                self._clear_checkpoint(label, url)
                break

            for item in new_items:
                seen_posts.add(item["post_url"])
                self.save_video(item, f"{label} p{page}")

            self._checkpoint(label, url, page)
            if self.state_path:
                key = self._state_key(label, url)
                self.state[key]["last_page_urls"] = [
                    item.get("post_url") for item in items if item.get("post_url")
                ]
                self._save_state()
            print(
                f"[{label}] page {page} complete | items={len(items)} new={len(new_items)} "
                f"added={self.stats['added']} duplicates={self.stats['duplicates']} "
                f"errors={self.stats['errors']}",
                flush=True,
            )

            if not items or not new_items:
                self._clear_checkpoint(label, url)
                break

            pagination = result.get("pagination", {})
            if not pagination.get("has_next"):
                break

            page += 1
            self.pause()

    def crawl_directory(self, kind, start_page=1, end_page=0):
        # /categories is a single directory page. The page range applies to
        # each /category/<slug> video listing discovered there.
        if kind == "category":
            directory = urljoin(BASE_URL, "/categories")
            result = self.provider.scrape_categories(directory, 1)
            self.stats["pages"] += 1
            entries = result.get("categories", [])

            for entry in entries:
                videos_url = entry.get("url") or urljoin(
                    BASE_URL + "/", f"category/{entry['slug']}"
                )
                self.crawl_listing(
                    videos_url,
                    f"category:{entry['slug']}",
                    start_page=start_page,
                    end_page=end_page,
                )
            return

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

                self.crawl_listing(
                    videos_url,
                    f"{kind}:{entry['slug']}",
                    start_page=1,
                    end_page=0,
                )

            pagination = result.get("pagination", {})
            if not entries or not new_entries:
                if entries and not new_entries:
                    print(
                        f"[{kind}-directory] page {page} contains only previously "
                        "seen entries; stopping pagination.",
                        flush=True,
                    )
                break
            if not pagination.get("has_next"):
                break

            page += 1
            self.pause()

    def crawl_url(self, url, start_page=1, end_page=0):
        """Crawl one user-selected URL with automatic page-type detection."""
        parsed = urlparse(url)
        path = parsed.path.rstrip("/").lower()

        if re.fullmatch(r"/actress/[^/]+", path):
            self.crawl_listing(url, f"actress:{path.rsplit('/', 1)[-1]}", start_page, end_page)
            return
        if re.fullmatch(r"/channel/[^/]+", path):
            self.crawl_listing(url, f"studio:{path.rsplit('/', 1)[-1]}", start_page, end_page)
            return
        if re.fullmatch(r"/category/[^/]+", path):
            self.crawl_listing(url, f"category:{path.rsplit('/', 1)[-1]}", start_page, end_page)
            return
        if path in ("/main", "/search"):
            self.crawl_listing(url, path.strip("/"), start_page, end_page)
            return
        if path == "/actresses":
            self.crawl_directory("actress", start_page, end_page)
            return
        if path == "/channels":
            self.crawl_directory("studio", start_page, end_page)
            return
        if path == "/categories":
            self.crawl_directory("category", start_page, end_page)
            return

        self.crawl_listing(url, "listing", start_page, end_page)

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

        if scope in ("all", "categories"):
            self.crawl_directory(
                "category",
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
    parser.add_argument("--scope", choices=("all", "main", "actresses", "studios", "categories"), default=None)
    parser.add_argument("--url", help="Specific actress, studio, category, or listing URL")
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--start-page", type=int, default=None)
    parser.add_argument("--end-page", type=int, default=None)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--database", default="database")
    parser.add_argument("--state-file", default="database/crawler_state.json")
    parser.add_argument("--resume", action="store_true", help="Resume from the saved checkpoint")
    args = parser.parse_args()

    # Default manual mode: ask for one URL and its page range.
    if not args.scope:
        url = args.url or input("Enter actress/studio/category/listing URL: ").strip()
        if not url:
            parser.error("A URL is required")

        start_page = args.start_page
        if start_page is None:
            raw = input("Start page [1]: ").strip()
            start_page = int(raw) if raw else 1

        end_page = args.end_page
        if end_page is None:
            raw = input("End page [auto]: ").strip()
            end_page = int(raw) if raw else 0

        if args.max_pages is not None and end_page == 0:
            end_page = start_page + args.max_pages - 1 if args.max_pages > 0 else 0

        if end_page and end_page < start_page:
            parser.error("End page must be greater than or equal to start page")

        manager = ProviderManager()
        provider = manager.resolve(BASE_URL)
        provider.timeout = args.timeout
        provider.retries = args.retries

        crawler = Crawler(provider, JsonDatabase(args.database), delay=args.delay, state_path=args.state_file, resume=args.resume, retries=args.retries)
        crawler.crawl_url(url, max(1, start_page), max(0, end_page))
        crawler.db.finalize(crawler.stats)
        print("\nCrawl complete:", crawler.stats, flush=True)
        return

    # Legacy multi-scope mode remains available for Actions/automation.
    start_page = max(1, args.start_page if args.start_page is not None else 1)
    end_page = max(0, args.end_page if args.end_page is not None else 0)

    if args.max_pages is not None and end_page == 0:
        end_page = start_page + args.max_pages - 1 if args.max_pages > 0 else 0

    if end_page and end_page < start_page:
        parser.error("End page must be greater than or equal to start page")

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
        state_path=args.state_file,
        resume=args.resume,
        retries=args.retries,
    )
    crawler.run(args.scope)


if __name__ == "__main__":
    raise SystemExit(main())
