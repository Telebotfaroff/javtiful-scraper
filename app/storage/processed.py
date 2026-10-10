"""Persistent duplicate tracking for Telegram uploads.

When GH_TOKEN/GITHUB_TOKEN and GITHUB_REPOSITORY are set, records are stored in
GitHub Contents API so they survive disposable GitHub Actions runners.
Without a token, the same format is stored locally for development only.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests

logger = logging.getLogger(__name__)


class ProcessedStoreError(RuntimeError):
    """Raised when persistent upload history cannot be read or saved."""


class ProcessedStore:
    def __init__(self):
        self.repo = os.getenv("GITHUB_REPOSITORY", "").strip()
        self.branch = os.getenv("PROCESSED_DB_BRANCH", os.getenv("GITHUB_REF_NAME", "javdl")).strip()
        self.path = os.getenv("PROCESSED_DB_PATH", "database/processed.json").strip().strip("/")
        self.token = (os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
        self.local_path = Path(self.path)
        self._lock = threading.RLock()
        self._loaded = False
        self._sha = None
        self._data = {"schema_version": 1, "uploaded": {}}
        self._in_progress = set()
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "JAVDL-ProcessedStore",
        })
        if self.token:
            self._session.headers["Authorization"] = f"Bearer {self.token}"
        else:
            logger.warning(
                "ProcessedStore has no GH_TOKEN/GITHUB_TOKEN; history is local-only "
                "and will not survive a fresh GitHub Actions runner."
            )

    @staticmethod
    def canonical_url(url):
        if not url:
            return ""
        parts = urlsplit(str(url).strip())
        path = parts.path.rstrip("/")
        # Query strings and fragments commonly contain tracking/pagination state.
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))

    @staticmethod
    def normalize_code(code):
        if not code:
            return ""
        return re.sub(r"[-_ ]+", "-", str(code).strip()).upper()

    @classmethod
    def key_for(cls, url, code=None):
        normalized_code = cls.normalize_code(code)
        if not normalized_code:
            canonical = cls.canonical_url(url)
            return "url:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return "code:" + normalized_code

    @property
    def _api_url(self):
        if not self.repo:
            raise ProcessedStoreError("GITHUB_REPOSITORY is not configured.")
        return f"https://api.github.com/repos/{self.repo}/contents/{self.path}"

    def _read_remote(self):
        response = self._session.get(
            self._api_url,
            params={"ref": self.branch},
            timeout=20,
        )
        if response.status_code == 404:
            return {"schema_version": 1, "uploaded": {}}, None
        if response.status_code >= 400:
            raise ProcessedStoreError(
                f"GitHub database read failed ({response.status_code}): {response.text[:300]}"
            )
        payload = response.json()
        try:
            raw = base64.b64decode(payload.get("content", "")).decode("utf-8")
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProcessedStoreError(f"GitHub database JSON is invalid: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("uploaded"), dict):
            raise ProcessedStoreError("GitHub database must contain an 'uploaded' object.")
        data.setdefault("schema_version", 1)
        return data, payload.get("sha")

    def _read_local(self):
        if not self.local_path.exists():
            return {"schema_version": 1, "uploaded": {}}, None
        try:
            data = json.loads(self.local_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ProcessedStoreError(f"Local processed database is invalid: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("uploaded"), dict):
            raise ProcessedStoreError("Local database must contain an 'uploaded' object.")
        data.setdefault("schema_version", 1)
        return data, None

    def _ensure_loaded(self):
        if self._loaded:
            return
        if self.token:
            self._data, self._sha = self._read_remote()
        else:
            self._data, self._sha = self._read_local()
        self._loaded = True

    def is_completed(self, url, code=None):
        key = self.key_for(url, code)
        with self._lock:
            self._ensure_loaded()
            record = self._data["uploaded"].get(key)
            if record and record.get("status") == "completed":
                return True
            # If the code was not supplied by the caller, also check the URL key.
            url_key = self.key_for(url)
            if url_key != key:
                record = self._data["uploaded"].get(url_key)
                return bool(record and record.get("status") == "completed")
            return False

    def claim(self, url, code=None):
        """Prevent duplicate work inside this bot process."""
        key = self.key_for(url, code)
        with self._lock:
            self._ensure_loaded()
            if self.is_completed(url, code) or key in self._in_progress:
                return False
            self._in_progress.add(key)
            return True

    def release(self, url, code=None):
        with self._lock:
            self._in_progress.discard(self.key_for(url, code))

    def mark_completed(self, url, code=None, title=None, destination="telegram", message_ids=None):
        key = self.key_for(url, code)
        record = {
            "status": "completed",
            "code": self.normalize_code(code) or None,
            "title": str(title or "").strip() or None,
            "url": self.canonical_url(url),
            "destination": destination,
            "telegram_message_ids": [int(value) for value in (message_ids or []) if str(value).isdigit()],
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._ensure_loaded()
            self._data["uploaded"][key] = record
            self.local_path.parent.mkdir(parents=True, exist_ok=True)
            self.local_path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if self.token:
                self._write_remote(key, record)
            self._in_progress.discard(key)
            logger.info("ProcessedStore: recorded completed upload key=%s", key)

    def _write_remote(self, key, record):
        # Re-read and merge before each write so the saved file is not based on
        # a stale SHA. Retry a few times if another write races this one.
        last_error = None
        for attempt in range(4):
            try:
                remote_data, sha = self._read_remote()
                remote_data.setdefault("uploaded", {})[key] = record
                encoded = base64.b64encode(
                    (json.dumps(remote_data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                ).decode("ascii")
                payload = {
                    "message": f"Track completed upload: {key}",
                    "content": encoded,
                    "branch": self.branch,
                }
                if sha:
                    payload["sha"] = sha
                response = self._session.put(self._api_url, json=payload, timeout=20)
                if response.status_code in (409, 422):
                    last_error = f"GitHub write conflict ({response.status_code})"
                    time.sleep(0.5 * (attempt + 1))
                    continue
                if response.status_code >= 400:
                    raise ProcessedStoreError(
                        f"GitHub database write failed ({response.status_code}): {response.text[:300]}"
                    )
                body = response.json()
                self._data = remote_data
                self._sha = (body.get("content") or {}).get("sha")
                return
            except requests.RequestException as exc:
                last_error = str(exc)
                time.sleep(0.5 * (attempt + 1))
        raise ProcessedStoreError(f"Could not persist upload history after retries: {last_error}")
