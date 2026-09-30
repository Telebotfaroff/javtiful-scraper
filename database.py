#!/usr/bin/env python3
"""Grouped JSON database for the metadata crawler."""

import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


class JsonDatabase:
    """Maintain compact category files instead of one file per video."""

    def __init__(self, root="database"):
        self.root = Path(root)
        self.index = self.root / "index"
        self.root.mkdir(parents=True, exist_ok=True)
        self.index.mkdir(parents=True, exist_ok=True)

        self.index_actress = self._load_index("indexactress.json", "actresses")
        self.index_studio = self._load_index("indexstudio.json", "studios")
        self.index_code = self._load_index("indexcode.json", "codes")
        self.seen_codes = set()
        self.seen_urls = set()
        self._load_existing_keys()

    @staticmethod
    def _load(path, default):
        try:
            with path.open("r", encoding="utf-8") as fh:
                value = json.load(fh)
            return value if isinstance(value, dict) else default
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return default

    def _load_index(self, filename, key):
        data = self._load(self.index / filename, {"total": 0, key: {}})
        if not isinstance(data.get(key), dict):
            data[key] = {}
        data["total"] = len(data[key])
        return data

    @staticmethod
    def canonical_url(url):
        if not url:
            return None
        parsed = urlsplit(str(url).strip())
        path = parsed.path.rstrip("/") or "/"
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))

    @staticmethod
    def safe_slug(value, fallback="unknown"):
        value = str(value or "").strip().lower()
        value = re.sub(r"[^a-z0-9_-]+", "-", value)
        value = re.sub(r"-+", "-", value).strip("-_")
        return value or fallback

    @staticmethod
    def code_category(code):
        return str(code).split("-", 1)[0].upper()

    def _load_existing_keys(self):
        code_root = self.root / "code"
        if not code_root.exists():
            return
        for path in code_root.glob("*/videos.json"):
            data = self._load(path, {"videos": {}})
            videos = data.get("videos", {})
            if not isinstance(videos, dict):
                continue
            for code, video in videos.items():
                self.seen_codes.add(str(code).upper())
                if isinstance(video, dict) and video.get("url"):
                    self.seen_urls.add(self.canonical_url(video["url"]))

    def contains(self, code=None, url=None):
        normalized_code = str(code or "").strip().upper() or None
        normalized_url = self.canonical_url(url)
        return (normalized_code and normalized_code in self.seen_codes) or (
            normalized_url and normalized_url in self.seen_urls
        )

    def normalize_video(self, raw):
        actresses = raw.get("actresses") or []
        normalized_actresses = []
        for actress in actresses:
            if isinstance(actress, dict):
                name = str(actress.get("name") or actress.get("slug") or "").strip()
                slug = self.safe_slug(actress.get("slug") or name)
            else:
                name = str(actress).strip()
                slug = self.safe_slug(name)
            if name and not any(a["slug"] == slug for a in normalized_actresses):
                normalized_actresses.append({"name": name, "slug": slug})

        code = str(raw.get("code") or "").strip().upper() or None
        url = self.canonical_url(raw.get("url") or raw.get("post_url"))
        studio = raw.get("studio")
        studio_slug = raw.get("studio_slug") or self.safe_slug(studio, "")

        return {
            "code": code,
            "title": str(raw.get("title") or "").strip(),
            "url": url,
            "thumb": raw.get("thumb") or raw.get("thumbnail"),
            "duration": raw.get("duration"),
            "date": raw.get("date"),
            "actresses": normalized_actresses,
            "studio": str(studio).strip() if studio else None,
            "studio_slug": self.safe_slug(studio_slug, "") if studio_slug else None,
            "genres": list(dict.fromkeys(str(x).strip() for x in (raw.get("genres") or []) if str(x).strip())),
        }

    def register_actress(self, entry):
        slug = self.safe_slug(entry.get("slug"), "")
        if not slug:
            return
        existing = self.index_actress["actresses"].get(slug, {})
        self.index_actress["actresses"][slug] = {
            "name": entry.get("name") or existing.get("name") or slug,
            "slug": slug,
            "url": entry.get("url") or existing.get("url") or f"https://javtiful.com/actress/{slug}",
            "thumbnail": entry.get("thumbnail") or existing.get("thumbnail"),
            "total_videos": existing.get("total_videos", 0),
            "total_pages": existing.get("total_pages", 0),
            "status": existing.get("status", "pending"),
            "last_crawled_page": existing.get("last_crawled_page", 0),
            "videos_crawled": existing.get("videos_crawled", 0),
            "last_crawled_at": existing.get("last_crawled_at"),
        }

    def register_studio(self, entry):
        slug = self.safe_slug(entry.get("slug"), "")
        if not slug:
            return
        existing = self.index_studio["studios"].get(slug, {})
        self.index_studio["studios"][slug] = {
            "name": entry.get("name") or existing.get("name") or slug,
            "slug": slug,
            "url": entry.get("url") or existing.get("url") or f"https://javtiful.com/channel/{slug}",
            "thumbnail": entry.get("thumbnail") or existing.get("thumbnail"),
            "total_videos": existing.get("total_videos", 0),
        }

    def add_video(self, raw):
        video = self.normalize_video(raw)
        code = video["code"]
        url = video["url"]
        if not code:
            return {"status": "skipped", "reason": "missing_code"}
        if self.contains(code, url):
            return {"status": "duplicate", "code": code}

        # Code index stores the full compact record.
        category = self.code_category(code)
        code_path = self.root / "code" / category / "videos.json"
        code_data = self._load(code_path, {"total": 0, "videos": {}})
        code_data.setdefault("videos", {})[code] = self._code_record(video)
        code_data["total"] = len(code_data["videos"])
        self._write(code_path, code_data)

        # Actress-specific files omit the redundant actresses field.
        for actress in video["actresses"]:
            slug = actress["slug"]
            path = self.root / "actress" / slug / "videos.json"
            data = self._load(path, {"total": 0, "videos": {}})
            data.setdefault("videos", {})[code] = self._actress_record(video)
            data["total"] = len(data["videos"])
            self._write(path, data)
            existing_index = self.index_actress["actresses"].get(slug, {})
            self.index_actress["actresses"][slug] = {
                "name": actress["name"],
                "slug": slug,
                "url": existing_index.get("url") or f"https://javtiful.com/actress/{slug}",
                "thumbnail": existing_index.get("thumbnail"),
                "total_videos": data["total"],
                "total_pages": existing_index.get("total_pages", 0),
                "status": existing_index.get("status", "pending"),
                "last_crawled_page": existing_index.get("last_crawled_page", 0),
                "videos_crawled": existing_index.get("videos_crawled", 0),
                "last_crawled_at": existing_index.get("last_crawled_at"),
            }

        # Studio-specific files omit the redundant studio field.
        if video["studio_slug"]:
            slug = video["studio_slug"]
            path = self.root / "studio" / slug / "videos.json"
            data = self._load(path, {"total": 0, "videos": {}})
            data.setdefault("videos", {})[code] = self._studio_record(video)
            data["total"] = len(data["videos"])
            self._write(path, data)
            self.index_studio["studios"][slug] = {
                "name": video["studio"],
                "slug": slug,
                "url": f"https://javtiful.com/channel/{slug}",
                "thumbnail": self.index_studio["studios"].get(slug, {}).get("thumbnail"),
                "total_videos": data["total"],
            }

        self.seen_codes.add(code)
        if url:
            self.seen_urls.add(url)
        self.index_code["codes"][category] = self._count_category(category)
        return {"status": "added", "code": code}

    @staticmethod
    def _code_record(video):
        return {
            "title": video["title"], "url": video["url"], "thumb": video["thumb"],
            "duration": video["duration"], "date": video["date"],
            "actresses": [a["name"] for a in video["actresses"]],
            "studio": video["studio"], "genres": video["genres"],
        }

    @staticmethod
    def _actress_record(video):
        return {
            "title": video["title"], "url": video["url"], "thumb": video["thumb"],
            "duration": video["duration"], "date": video["date"],
            "studio": video["studio_slug"] or video["studio"], "genres": video["genres"],
        }

    @staticmethod
    def _studio_record(video):
        return {
            "title": video["title"], "url": video["url"], "thumb": video["thumb"],
            "duration": video["duration"], "date": video["date"],
            "actresses": [a["name"] for a in video["actresses"]], "genres": video["genres"],
        }

    def _count_category(self, category):
        path = self.root / "code" / category / "videos.json"
        data = self._load(path, {"videos": {}})
        return len(data.get("videos", {}))

    def finalize(self, stats):
        self.index_actress["total"] = len(self.index_actress["actresses"])
        self.index_studio["total"] = len(self.index_studio["studios"])
        self.index_code["total"] = len(self.index_code["codes"])
        self._write(self.index / "indexactress.json", self.index_actress)
        self._write(self.index / "indexstudio.json", self.index_studio)
        self._write(self.index / "indexcode.json", self.index_code)
        master = {
            "version": 1,
            "total_videos": len(self.seen_codes),
            "total_actresses": self.index_actress["total"],
            "total_studios": self.index_studio["total"],
            "total_code_categories": self.index_code["total"],
            "last_run": stats,
        }
        self._write(self.index / "database.json", master)

    @staticmethod
    def _write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".json-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=False)
                fh.write("\n")
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
