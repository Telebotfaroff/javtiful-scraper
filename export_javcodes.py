#!/usr/bin/env python3
"""Export video codes from a Javtiful actress, channel, or category listing.

Output files are plain text: one clean video code per line, with at most 100
codes per file. Titles and other metadata are intentionally omitted.
"""

import argparse
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

from providers.javtiful import JavtifulProvider


def url_slug(url):
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[-2].lower() not in {"actress", "channel", "category"}:
        raise ValueError(
            "URL must be a Javtiful actress, channel, or category page, "
            "for example /actress/example, /channel/example, or /category/example."
        )
    slug = parts[-1]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", slug).strip("-.")
    if not slug:
        raise ValueError("Could not derive a safe folder name from the URL.")
    return slug


def normalize_code(value):
    if not isinstance(value, str):
        return None
    code = re.sub(r"\\s+", "-", value.strip().upper())
    if re.fullmatch(r"[A-Z0-9]{2,8}-[A-Z0-9]{2,8}(?:-[A-Z0-9]{1,8})?", code):
        return code
    return None


def load_existing_codes(output_root, exclude_dir):
    """Read codes from other export folders to prevent cross-folder duplicates."""
    existing = set()
    excluded = os.path.abspath(exclude_dir)

    if not os.path.isdir(output_root):
        return existing

    for root, _, filenames in os.walk(output_root):
        if os.path.abspath(root) == excluded:
            continue
        for filename in filenames:
            if not re.fullmatch(r"codes-\\d{3,}\\.(?:txt|json)", filename):
                continue
            path = os.path.join(root, filename)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    content = handle.read()
                if filename.endswith(".json"):
                    try:
                        values = json.loads(content)
                        if isinstance(values, list):
                            for value in values:
                                code = normalize_code(value)
                                if code:
                                    existing.add(code)
                            continue
                    except json.JSONDecodeError:
                        pass
                for line in content.splitlines():
                    code = normalize_code(line)
                    if code:
                        existing.add(code)
            except (OSError, UnicodeError) as exc:
                print(f"WARNING: Could not read existing code file {path}: {exc}", flush=True)

    return existing


def export_codes(url, output_root, chunk_size=100, delay=0.5, timeout=30, retries=2, max_pages=10000):
    provider = JavtifulProvider(timeout=timeout, retries=retries)
    slug = url_slug(url)
    output_dir = os.path.join(output_root, slug)
    seen_codes = load_existing_codes(output_root, output_dir)
    codes = []
    valid_codes_found = 0
    duplicates_skipped = 0
    previous_page_signature = None
    pages_scraped = 0

    try:
        for page in range(1, max_pages + 1):
            print(f"[page {page}] Fetching listing...", flush=True)
            result = provider.scrape_listing(url, page=page, enrich=False)
            items = result.get("items") or []
            signature = tuple(
                item.get("post_url") or item.get("code") or ""
                for item in items
            )

            # Some listing pages return the final page for out-of-range requests.
            if not items:
                print(f"[page {page}] No items; pagination complete.", flush=True)
                break
            if signature and signature == previous_page_signature:
                print(f"[page {page}] Repeated previous page; stopping safely.", flush=True)
                break
            previous_page_signature = signature
            pages_scraped += 1

            added_this_page = 0
            for item in items:
                code = item.get("code")
                if not isinstance(code, str):
                    continue
                code = re.sub(r"\s+", "-", code.strip().upper())
                if not re.fullmatch(r"[A-Z0-9]{2,8}-[A-Z0-9]{2,8}(?:-[A-Z0-9]{1,8})?", code):
                    continue
                if code in seen_codes:
                    continue
                seen_codes.add(code)
                codes.append(code)
                added_this_page += 1

            print(
                f"[page {page}] cards={len(items)} new_codes={added_this_page} "
                f"unique_total={len(codes)}",
                flush=True,
            )

            if delay > 0:
                time.sleep(delay)
        else:
            raise RuntimeError(f"Reached safety limit of {max_pages} pages.")

        if valid_codes_found == 0:
            raise RuntimeError(
                "No valid video codes were extracted. Check the URL and the page's listing structure."
            )

        if not codes:
            print(
                f"All {duplicates_skipped} valid codes already exist in other Javcode folders; "
                "nothing new to save.",
                flush=True,
            )
            return

        os.makedirs(output_dir, exist_ok=True)

        # Remove old numbered chunks so a shorter refresh cannot leave stale codes.
        for name in os.listdir(output_dir):
            if re.fullmatch(r"codes-\d{3,}\.(?:json|txt)", name):
                os.remove(os.path.join(output_dir, name))

        for offset in range(0, len(codes), chunk_size):
            chunk_number = offset // chunk_size + 1
            path = os.path.join(output_dir, f"codes-{chunk_number:03d}.txt")
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("\n".join(codes[offset:offset + chunk_size]) + "\n")
            print(f"Saved {min(chunk_size, len(codes) - offset)} codes -> {path}", flush=True)

        print(
            json.dumps(
                {
                    "url": url,
                    "slug": slug,
                    "pages_scraped": pages_scraped,
                    "total_new_unique_codes": len(codes),
                    "duplicates_skipped": duplicates_skipped,
                    "files_written": (len(codes) + chunk_size - 1) // chunk_size,
                    "output_dir": output_dir,
                },
                indent=2,
            ),
            flush=True,
        )
    finally:
        provider.session.close()


def main():
    parser = argparse.ArgumentParser(description="Export video codes from a Javtiful listing URL.")
    parser.add_argument("--url", required=True, help="Actress, channel, or category URL")
    parser.add_argument("--output-root", default="Javcode", help="Output root folder (default: Javcode)")
    parser.add_argument("--chunk-size", type=int, default=100, help="Codes per TXT file (maximum 100)")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between page requests in seconds")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")
    parser.add_argument("--retries", type=int, default=2, help="HTTP retries")
    parser.add_argument("--max-pages", type=int, default=10000, help="Safety limit for pagination")
    args = parser.parse_args()

    parsed = urlparse(args.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc.lower().endswith("javtiful.com"):
        parser.error("--url must be an HTTP(S) URL on javtiful.com")
    if args.chunk_size < 1 or args.chunk_size > 100:
        parser.error("--chunk-size must be between 1 and 100")
    if args.timeout < 1 or args.retries < 0 or args.max_pages < 1:
        parser.error("--timeout and --max-pages must be positive; --retries cannot be negative")

    try:
        export_codes(
            args.url,
            args.output_root,
            chunk_size=args.chunk_size,
            delay=max(0.0, args.delay),
            timeout=args.timeout,
            retries=args.retries,
            max_pages=args.max_pages,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
