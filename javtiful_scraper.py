#!/usr/bin/env python3

import argparse
import json
import re
import sys
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://javtiful.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
}


class JavtifulScraper:
    """Python implementation of the Javtiful listing/post extraction architecture."""

    def __init__(self, timeout=30, retries=2):
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    @staticmethod
    def clean(value):
        if not value:
            return None
        return re.sub(r"\s+", " ", str(value)).strip() or None

    @staticmethod
    def absolute(base, value):
        return urljoin(base, value) if value else None

    @staticmethod
    def page_url(base, page):
        if page <= 1:
            return base
        parsed = urlparse(base)
        query = parse_qs(parsed.query, keep_blank_values=True)
        query["page"] = [str(page)]
        return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

    def fetch(self, url):
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(
                    url, timeout=self.timeout, allow_redirects=True
                )
                response.raise_for_status()
                if len(response.text) < 100:
                    raise requests.RequestException("Empty or malformed response")
                return response.url, response.text
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.retries:
                    import time
                    time.sleep(1 * (2 ** attempt))
        raise last_error

    def soup(self, html):
        return BeautifulSoup(html, "lxml")

    def json_ld(self, soup):
        items = []
        for script in soup.select('script[type="application/ld+json"]'):
            raw = script.string or script.get_text()
            try:
                data = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            items.extend(data if isinstance(data, list) else [data])
        return [x for x in items if isinstance(x, dict)]

    def meta(self, soup, name=None, prop=None):
        attrs = {"name": name} if name else {"property": prop}
        tag = soup.find("meta", attrs=attrs)
        return self.clean(tag.get("content")) if tag else None

    def title(self, soup, ld):
        for item in ld:
            if item.get("name"):
                return self.clean(item["name"])
        return self.meta(soup, prop="og:title") or (
            self.clean(soup.title.get_text()) if soup.title else None
        )

    def description(self, soup, ld):
        for item in ld:
            if item.get("description"):
                return self.clean(item["description"])
        return self.meta(soup, prop="og:description") or self.meta(
            soup, name="description"
        )

    def image(self, base, soup, ld):
        for item in ld:
            image = item.get("image")
            if isinstance(image, str):
                return self.absolute(base, image)
            if isinstance(image, list) and image:
                return self.absolute(base, image[0])
            if isinstance(image, dict):
                return self.absolute(base, image.get("url"))
        return self.absolute(base, self.meta(soup, prop="og:image"))

    def parse_duration(self, raw):
        raw = self.clean(raw)
        if not raw:
            return None, 0

        iso = re.fullmatch(
            r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", raw, re.I
        )
        if iso:
            h = int(iso.group(1) or 0)
            m = int(iso.group(2) or 0)
            s = int(iso.group(3) or 0)
            return f"{h:02d}:{m:02d}:{s:02d}", h * 3600 + m * 60 + s

        parts = raw.split(":")
        if all(p.strip().isdigit() for p in parts):
            nums = [int(p.strip()) for p in parts]
            if len(nums) == 3:
                return f"{nums[0]:02d}:{nums[1]:02d}:{nums[2]:02d}", nums[0] * 3600 + nums[1] * 60 + nums[2]
            if len(nums) == 2:
                return f"00:{nums[0]:02d}:{nums[1]:02d}", nums[0] * 60 + nums[1]

        return raw, 0

    def extract_code(self, title, post_url):
        # Match the original project's URL-first strategy.
        slug_match = re.search(
            r"/video/\d+/([a-zA-Z0-9]+[\-_][a-zA-Z0-9]+(?:[\-_][a-zA-Z0-9]+)?)",
            post_url,
            re.I,
        )
        if slug_match:
            raw = slug_match.group(1).strip()
            normalized = self.normalize_code(raw)
            if normalized:
                return normalized, raw

        patterns = (
            r"^([a-zA-Z0-9]+[\s\-_]+[a-zA-Z0-9]+(?:[\s\-_]+[a-zA-Z0-9]+)?)",
            r"\b([A-Z]{2,8}[-_ ]?\d{2,7})\b",
        )
        for pattern in patterns:
            match = re.search(pattern, title or "", re.I)
            if match:
                raw = match.group(1).strip()
                normalized = self.normalize_code(raw)
                if normalized:
                    return normalized, raw

        return None, None

    @staticmethod
    def normalize_code(raw):
        if not raw:
            return None
        value = re.sub(r"[\s_]+", "-", raw.strip().upper())
        value = re.sub(r"-+", "-", value)
        if re.fullmatch(r"[A-Z0-9]{2,8}-[A-Z0-9]{2,8}(?:-[A-Z0-9]{1,8})?", value):
            return value
        return None

    def parse_card(self, card, base):
        title_link = card.select_one(
            ".front-video-title, .video-title, h2 a, h3 a, h4 a"
        )
        thumb_link = card.select_one(".front-video-thumb, .thumb, a")

        title = (
            self.clean(title_link.get_text())
            if title_link
            else self.clean((thumb_link.get("title") if thumb_link else None))
            or self.clean((card.find("img").get("alt") if card.find("img") else None))
        )

        raw_href = (
            title_link.get("href")
            if title_link and title_link.get("href")
            else thumb_link.get("href")
            if thumb_link
            else None
        )
        post_url = self.absolute(base, raw_href)
        if not post_url or "/video/" not in post_url:
            return None

        img = card.find("img")
        cover = None
        if img:
            cover = (
                img.get("data-front-lazy-src")
                or img.get("data-src")
                or img.get("src")
            )

        duration_raw = None
        duration_el = card.select_one(".front-duration-tag, .duration, .time")
        if duration_el:
            duration_raw = duration_el.get_text()
        duration, duration_seconds = self.parse_duration(duration_raw)

        actress_el = card.select_one('a[href*="/actress/"]')
        actress_name = self.clean(actress_el.get_text()) if actress_el else None
        actress_slug = None
        if actress_el and actress_el.get("href"):
            actress_slug = self.slug_from_href(actress_el["href"], "/actress/")

        studio_el = card.select_one('a[href*="/channel/"]')
        studio_name = self.clean(studio_el.get_text()) if studio_el else None
        studio_slug = None
        if studio_el and studio_el.get("href"):
            studio_slug = self.slug_from_href(studio_el["href"], "/channel/")

        code, raw_code = self.extract_code(title, post_url)

        return {
            "code": code,
            "raw_code": raw_code,
            "title": title,
            "actress": actress_name,
            "actress_slug": actress_slug,
            "studio": studio_name,
            "studio_slug": studio_slug,
            "duration": duration,
            "duration_seconds": duration_seconds,
            "thumbnail": self.absolute(base, cover),
            "post_url": post_url,
        }

    @staticmethod
    def slug_from_href(href, marker):
        value = href.split(marker, 1)[-1].strip("/")
        return value or None

    def parse_cards(self, html, base):
        soup = self.soup(html)
        items = []
        seen = set()

        cards = soup.select(".front-video-card, .video-card, .video-item")
        for card in cards:
            item = self.parse_card(card, base)
            if not item or item["post_url"] in seen:
                continue
            seen.add(item["post_url"])
            items.append(item)

        # Same fallback used by the original project when card selectors fail.
        if not items:
            for anchor in soup.select('a[href*="/video/"]'):
                href = anchor.get("href")
                post_url = self.absolute(base, href)
                if not post_url or post_url in seen:
                    continue
                title = self.clean(anchor.get_text()) or self.clean(anchor.get("title"))
                if not title or len(title) < 5:
                    continue
                img = anchor.find("img")
                cover = img.get("data-front-lazy-src") if img else None
                cover = cover or (img.get("src") if img else None)
                code, raw_code = self.extract_code(title, post_url)
                seen.add(post_url)
                items.append({
                    "code": code,
                    "raw_code": raw_code,
                    "title": title,
                    "actress": None,
                    "actress_slug": None,
                    "studio": None,
                    "studio_slug": None,
                    "duration": None,
                    "duration_seconds": 0,
                    "thumbnail": self.absolute(base, cover),
                    "post_url": post_url,
                })

        return items

    def parse_pagination(self, soup, current_page=1):
        max_page = current_page
        has_next = False

        selectors = (
            "nav.front-pagination a.front-pagination-link",
            ".pagination a",
            'nav a[href*="page="]',
        )
        for link in soup.select(", ".join(selectors)):
            text = self.clean(link.get_text()) or ""
            href = link.get("href") or ""
            match = re.search(r"[?&]page=(\d+)", href, re.I)
            if match:
                max_page = max(max_page, int(match.group(1)))
            if text.isdigit():
                max_page = max(max_page, int(text))
            if "next" in text.lower():
                has_next = True

        has_next = has_next or current_page < max_page
        return {
            "current_page": current_page,
            "total_pages": max_page,
            "has_next": has_next,
            "has_prev": current_page > 1,
            "next_page": current_page + 1 if has_next else None,
            "prev_page": current_page - 1 if current_page > 1 else None,
        }

    def enrich_post(self, url):
        final_url, html = self.fetch(url)
        soup = self.soup(html)
        ld = self.json_ld(soup)

        video_ld = next(
            (
                item for item in ld
                if item.get("@type") == "VideoObject"
            ),
            {},
        )

        title = (
            self.clean(soup.select_one("h1").get_text())
            if soup.select_one("h1")
            else video_ld.get("name")
            or self.meta(soup, prop="og:title")
        )
        code, raw_code = self.extract_code(title, final_url)

        actresses = []
        for link in soup.select('a[href*="/actress/"]'):
            name = self.clean(link.get_text())
            slug = self.slug_from_href(link.get("href", ""), "/actress/")
            if name and slug and not any(x["slug"] == slug for x in actresses):
                actresses.append({"name": name, "slug": slug})

        studio_name = None
        studio_slug = None
        for link in soup.select('a[href*="/channel/"]'):
            name = self.clean(link.get_text())
            slug = self.slug_from_href(link.get("href", ""), "/channel/")
            if name and slug:
                studio_name, studio_slug = name, slug
                break

        release_date = None
        if video_ld.get("uploadDate"):
            release_date = str(video_ld["uploadDate"]).split("T")[0]
        else:
            detail = soup.select_one(".front-watch-detail")
            if detail:
                text = self.clean(detail.get_text()) or ""
                match = re.search(r"Added on:\s*(.+)", text, re.I)
                if match:
                    release_date = self.clean(match.group(1))

        duration_raw = video_ld.get("duration")
        if not duration_raw:
            duration_el = soup.select_one(".front-duration-tag")
            duration_raw = duration_el.get_text() if duration_el else None
        duration, duration_seconds = self.parse_duration(duration_raw)

        thumbnail = (
            video_ld.get("thumbnailUrl")
            if isinstance(video_ld.get("thumbnailUrl"), str)
            else (video_ld.get("thumbnailUrl") or [None])[0]
        )
        thumbnail = thumbnail or self.meta(soup, prop="og:image")
        thumbnail = self.absolute(final_url, thumbnail)

        return {
            "url": final_url,
            "code": code,
            "raw_code": raw_code,
            "title": title,
            "date": release_date,
            "duration": duration,
            "duration_seconds": duration_seconds,
            "thumbnail": thumbnail,
            "actresses": actresses,
            "studio": studio_name,
            "studio_slug": studio_slug,
            "description": self.description(soup, ld),
            "genres": self.genres(soup),
            "video_sources": self.video_sources(final_url, soup),
        }

    def genres(self, soup):
        genres = []
        seen = set()
        for link in soup.select('a[href*="/genre/"]'):
            name = self.clean(link.get_text())
            slug = self.slug_from_href(link.get("href", ""), "/genre/")
            value = name or slug
            if value and value.lower() not in seen:
                seen.add(value.lower())
                genres.append(value)
        if genres:
            return genres

        for item in soup.select(".genre, .genres a, [class*='genre'] a"):
            value = self.clean(item.get_text())
            if value and value.lower() not in seen:
                seen.add(value.lower())
                genres.append(value)
        return genres

    def video_sources(self, base, soup):
        sources = []
        seen = set()
        for tag in soup.select("video source, video[src], source[src], a[href]"):
            value = tag.get("src") or tag.get("href")
            if not value:
                continue
            absolute = self.absolute(base, value)
            if not absolute or absolute in seen:
                continue
            lower = absolute.lower()
            if any(ext in lower for ext in (".mp4", ".m3u8", ".webm", ".mkv")) or tag.name in ("source", "video"):
                seen.add(absolute)
                sources.append(absolute)
        return sources

    def scrape_listing(self, url, page=1, enrich=False, max_enrich=None):
        requested_url = self.page_url(url, page)
        final_url, html = self.fetch(requested_url)
        soup = self.soup(html)
        items = self.parse_cards(html, final_url)

        if enrich:
            targets = items if max_enrich is None else items[:max_enrich]
            for item in targets:
                try:
                    details = self.enrich_post(item["post_url"])
                    item.update({
                        "code": details["code"] or item["code"],
                        "title": details["title"] or item["title"],
                        "date": details["date"],
                        "duration": details["duration"] or item["duration"],
                        "duration_seconds": details["duration_seconds"] or item["duration_seconds"],
                        "thumbnail": details["thumbnail"] or item["thumbnail"],
                        "actresses": details["actresses"],
                        "studio": details["studio"] or item["studio"],
                        "studio_slug": details["studio_slug"] or item["studio_slug"],
                    })
                except requests.RequestException as exc:
                    item["enrichment_error"] = str(exc)

        return {
            "type": "listing",
            "url": final_url,
            "page": page,
            "total_found": len(items),
            "items": items,
            "pagination": self.parse_pagination(soup, page),
        }

    def scrape_actresses(self, url, page=1):
        requested_url = self.page_url(url, page)
        final_url, html = self.fetch(requested_url)
        soup = self.soup(html)
        actresses = []
        seen = set()

        for link in soup.select('a[href*="/actress/"]'):
            href = link.get("href", "")
            slug = self.slug_from_href(href, "/actress/")
            if not slug or slug in seen or slug == "actresses":
                continue
            seen.add(slug)

            text = self.clean(link.get_text()) or slug
            count_match = re.search(r"(\d+)\s+Videos?", text, re.I)
            count = int(count_match.group(1)) if count_match else None
            name = self.clean(re.sub(r"\d+\s+Videos?", "", text, flags=re.I)) or slug
            img = link.find("img")
            thumb = img.get("data-front-lazy-src") if img else None
            thumb = thumb or (img.get("src") if img else None)

            actresses.append({
                "name": name,
                "slug": slug,
                "video_count": count,
                "url": self.absolute(final_url, href),
                "thumbnail": self.absolute(final_url, thumb),
            })

        return {
            "type": "actress_directory",
            "url": final_url,
            "page": page,
            "total_found": len(actresses),
            "actresses": actresses,
            "pagination": self.parse_pagination(soup, page),
        }

    def scrape_studios(self, url, page=1):
        requested_url = self.page_url(url, page)
        final_url, html = self.fetch(requested_url)
        soup = self.soup(html)
        studios = []
        seen = set()

        for link in soup.select('a[href*="/channel/"]'):
            href = link.get("href", "")
            slug = self.slug_from_href(href, "/channel/")
            if not slug or slug in seen or slug == "channels":
                continue
            seen.add(slug)

            text = self.clean(link.get_text()) or slug
            count_match = re.search(r"(\d+)\s+Videos?", text, re.I)
            count = int(count_match.group(1)) if count_match else None
            name = self.clean(re.sub(r"\d+\s+Videos?", "", text, flags=re.I)) or slug
            img = link.find("img")
            thumb = img.get("data-front-lazy-src") if img else None
            thumb = thumb or (img.get("src") if img else None)

            studios.append({
                "name": name,
                "slug": slug,
                "video_count": count,
                "url": self.absolute(final_url, href),
                "thumbnail": self.absolute(final_url, thumb),
            })

        return {
            "type": "studio_directory",
            "url": final_url,
            "page": page,
            "total_found": len(studios),
            "studios": studios,
            "pagination": self.parse_pagination(soup, page),
        }

    def scrape_url(self, url, enrich=False, max_enrich=None):
        parsed = urlparse(url)
        path = parsed.path.rstrip("/").lower()

        if re.fullmatch(r"/actresses", path):
            return self.scrape_actresses(url)
        if re.fullmatch(r"/channels", path):
            return self.scrape_studios(url)
        if re.fullmatch(r"/actress/[^/]+", path):
            return self.scrape_listing(url, enrich=enrich, max_enrich=max_enrich)
        if re.fullmatch(r"/channel/[^/]+", path):
            return self.scrape_listing(url, enrich=enrich, max_enrich=max_enrich)
        if "/video/" in path:
            return {"type": "post", **self.enrich_post(url)}

        # /main, /search, category pages, and other listing pages use the shared card parser.
        return self.scrape_listing(url, enrich=enrich, max_enrich=max_enrich)

    # Backward-compatible method used by the original CLI.
    def scrape(self, url):
        return self.scrape_url(url)


def main():
    parser = argparse.ArgumentParser(
        description="Scrape Javtiful post, homepage/listing, actress, and studio/channel metadata"
    )
    parser.add_argument("url", help="Javtiful URL")
    parser.add_argument("-o", "--output", help="Write JSON result to this file")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--no-enrich", action="store_true", help="Do not open individual video pages for listing items")
    parser.add_argument("--max-enrich", type=int, default=None, help="Maximum listing items to enrich")
    parser.add_argument("--page", type=int, default=None, help="Override listing/directory page number")
    args = parser.parse_args()

    scraper = JavtifulScraper(timeout=args.timeout)

    try:
        if args.page:
            parsed = urlparse(args.url)
            path = parsed.path.rstrip("/").lower()
            if path == "/actresses":
                result = scraper.scrape_actresses(args.url, args.page)
            elif path == "/channels":
                result = scraper.scrape_studios(args.url, args.page)
            else:
                result = scraper.scrape_listing(
                    args.url,
                    args.page,
                    enrich=not args.no_enrich,
                    max_enrich=args.max_enrich,
                )
        else:
            result = scraper.scrape_url(
                args.url,
                enrich=not args.no_enrich,
                max_enrich=args.max_enrich,
            )
    except requests.RequestException as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Scraping failed: {exc}", file=sys.stderr)
        return 1

    output = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(output)
        print(f"Saved: {args.output}")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
