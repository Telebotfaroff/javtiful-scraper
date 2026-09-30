#!/usr/bin/env python3

import argparse
import json
import re
import sys
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class JavtifulScraper:
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    @staticmethod
    def clean(value):
        if not value:
            return None
        return re.sub(r"\\s+", " ", str(value)).strip() or None

    @staticmethod
    def absolute(base, value):
        return urljoin(base, value) if value else None

    def fetch(self, url):
        response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        response.raise_for_status()
        return response.url, response.text

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
        return self.meta(soup, prop="og:title") or self.clean(soup.title.get_text()) if soup.title else self.meta(soup, prop="og:title")

    def description(self, soup, ld):
        for item in ld:
            if item.get("description"):
                return self.clean(item["description"])
        return self.meta(soup, prop="og:description") or self.meta(soup, name="description")

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

    def date(self, soup, ld):
        for item in ld:
            for key in ("uploadDate", "datePublished", "dateCreated", "releaseDate"):
                if item.get(key):
                    return self.clean(item[key])
        tag = soup.find("time")
        if tag:
            return self.clean(tag.get("datetime") or tag.get_text())
        text = soup.get_text(" ", strip=True)
        for pattern in (r"\\b\\d{4}-\\d{2}-\\d{2}\\b", r"\\b\\d{4}/\\d{2}/\\d{2}\\b", r"\\b\\d{1,2}/\\d{1,2}/\\d{4}\\b"):
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return None

    def code(self, soup, title=None):
        sources = [title or "", soup.get_text(" ", strip=True)]
        patterns = (r"\\b[A-Z]{2,8}-\\d{2,6}\\b", r"\\b[A-Z]{2,8}\\d{3,6}\\b")
        for source in sources:
            for pattern in patterns:
                match = re.search(pattern, source.upper())
                if match:
                    return match.group(0)
        return None

    def duration(self, soup, ld):
        for item in ld:
            for key in ("duration", "timeRequired"):
                if item.get(key):
                    return self.clean(item[key])
        for tag in soup.find_all("time"):
            text = self.clean(tag.get_text())
            if text and re.search(r"\\b\\d+\\s*(?:min|mins|minutes|h|hr|hours)\\b", text, re.I):
                return text
        return None

    def actresses(self, soup):
        values = []
        for link in soup.find_all("a", href=True):
            text = self.clean(link.get_text())
            if text and "/actress/" in link["href"].lower() and text not in values:
                values.append(text)
        return values

    def studio(self, soup):
        for link in soup.find_all("a", href=True):
            if "/studio/" in link["href"].lower():
                return self.clean(link.get_text())
        return None

    def genres(self, soup):
        values = []
        for link in soup.find_all("a", href=True):
            href = link["href"].lower()
            text = self.clean(link.get_text())
            if text and any(x in href for x in ("/genre/", "/tag/", "/category/")) and text not in values:
                values.append(text)
        return values

    def video_sources(self, base, soup):
        values = []
        for tag in soup.find_all(["video", "source", "iframe"]):
            src = tag.get("src")
            if src:
                absolute = self.absolute(base, src)
                if absolute and absolute not in values:
                    values.append(absolute)
        return values

    def scrape(self, url):
        final_url, html = self.fetch(url)
        soup = BeautifulSoup(html, "lxml")
        ld = self.json_ld(soup)
        title = self.title(soup, ld)
        return {
            "url": final_url,
            "code": self.code(soup, title),
            "title": title,
            "date": self.date(soup, ld),
            "duration": self.duration(soup, ld),
            "thumbnail": self.image(final_url, soup, ld),
            "actresses": self.actresses(soup),
            "studio": self.studio(soup),
            "genres": self.genres(soup),
            "description": self.description(soup, ld),
            "video_sources": self.video_sources(final_url, soup),
        }


def main():
    parser = argparse.ArgumentParser(description="Scrape metadata from a Javtiful page")
    parser.add_argument("url")
    parser.add_argument("-o", "--output")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    try:
        result = JavtifulScraper(args.timeout).scrape(args.url)
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
