"""Neon PostgreSQL-backed upload history.

Only non-secret metadata belongs in this database. Telegram tokens, API hashes,
GitHub tokens, and other credentials must remain in Colab/GitHub Secrets.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row
from app.storage.processed import ProcessedStoreError

logger = logging.getLogger(__name__)


class NeonProcessedStore:
    """Drop-in implementation of the ProcessedStore API using Neon PostgreSQL."""

    def __init__(self, database_url=None):
        self.database_url = (database_url or os.getenv("DATABASE_URL", "")).strip()
        if not self.database_url:
            raise ProcessedStoreError(
                "DATABASE_URL is missing. Add your Neon connection string to Colab Secrets "
                "or GitHub Actions Secrets."
            )
        self._lock = threading.RLock()
        self._in_progress = set()
        self._initialized = False

    @staticmethod
    def canonical_url(url):
        if not url:
            return ""
        parts = urlsplit(str(url).strip())
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))

    @staticmethod
    def normalize_code(code):
        return re.sub(r"[-_ ]+", "-", str(code).strip()).upper() if code else ""

    @classmethod
    def key_for(cls, url, code=None):
        normalized_code = cls.normalize_code(code)
        if normalized_code:
            return "code:" + normalized_code
        canonical = cls.canonical_url(url)
        return "url:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _connect(self):
        return psycopg.connect(self.database_url, connect_timeout=10, row_factory=dict_row)

    def initialize(self):
        with self._lock:
            if self._initialized:
                return
            try:
                with self._connect() as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS javdl_upload_history (
                            source_key TEXT PRIMARY KEY,
                            canonical_url TEXT NOT NULL DEFAULT '',
                            code TEXT,
                            title TEXT,
                            status TEXT NOT NULL DEFAULT 'completed',
                            destination TEXT NOT NULL DEFAULT 'telegram',
                            telegram_message_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                            uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS javdl_upload_history_uploaded_at_idx
                        ON javdl_upload_history (uploaded_at DESC)
                    """)
            except Exception as exc:
                raise ProcessedStoreError(f"Neon upload-history initialization failed ({type(exc).__name__}).") from exc
            self._initialized = True

    def _ensure_loaded(self):
        self.initialize()

    def is_completed(self, url, code=None):
        self.initialize()
        keys = {self.key_for(url, code), self.key_for(url)}
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM javdl_upload_history WHERE source_key = ANY(%s) AND status = 'completed' LIMIT 1",
                    (list(keys),),
                ).fetchone()
            return row is not None
        except Exception as exc:
            raise ProcessedStoreError(f"Neon history read failed ({type(exc).__name__}).") from exc

    def claim(self, url, code=None):
        keys = {self.key_for(url, code), self.key_for(url)}
        with self._lock:
            if self.is_completed(url, code) or keys.intersection(self._in_progress):
                return False
            self._in_progress.update(keys)
            return True

    def release(self, url, code=None):
        with self._lock:
            self._in_progress.discard(self.key_for(url, code))
            self._in_progress.discard(self.key_for(url))

    def mark_completed(self, url, code=None, title=None, destination="telegram", message_ids=None):
        self.initialize()
        key = self.key_for(url, code)
        uploaded_at = datetime.now(timezone.utc)
        ids = [int(value) for value in (message_ids or []) if str(value).isdigit()]
        try:
            with self._connect() as conn:
                conn.execute("""
                    INSERT INTO javdl_upload_history
                        (source_key, canonical_url, code, title, status, destination,
                         telegram_message_ids, uploaded_at, updated_at)
                    VALUES (%s, %s, %s, %s, 'completed', %s, %s::jsonb, %s, NOW())
                    ON CONFLICT (source_key) DO UPDATE SET
                        canonical_url = EXCLUDED.canonical_url,
                        code = EXCLUDED.code,
                        title = EXCLUDED.title,
                        status = 'completed',
                        destination = EXCLUDED.destination,
                        telegram_message_ids = EXCLUDED.telegram_message_ids,
                        uploaded_at = EXCLUDED.uploaded_at,
                        updated_at = NOW()
                """, (
                    key, self.canonical_url(url), self.normalize_code(code) or None,
                    str(title or "").strip() or None, str(destination or "telegram"),
                    json.dumps(ids), uploaded_at,
                ))
        except Exception as exc:
            raise ProcessedStoreError(f"Neon history write failed ({type(exc).__name__}).") from exc
        finally:
            self.release(url, code)
        logger.info("Neon upload history recorded key=%s", key)

    def summary(self):
        self.initialize()
        try:
            with self._connect() as conn:
                row = conn.execute("""
                    SELECT COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE status = 'completed') AS completed
                    FROM javdl_upload_history
                """).fetchone()
            total, completed = int(row["total"]), int(row["completed"])
            return {"total": total, "completed": completed, "other": total - completed}
        except Exception as exc:
            raise ProcessedStoreError(f"Neon history summary failed ({type(exc).__name__}).") from exc

    def recent_completed(self, limit=5):
        self.initialize()
        limit = max(1, min(int(limit), 20))
        try:
            with self._connect() as conn:
                rows = conn.execute("""
                    SELECT title, code, uploaded_at, destination
                    FROM javdl_upload_history
                    WHERE status = 'completed'
                    ORDER BY uploaded_at DESC
                    LIMIT %s
                """, (limit,)).fetchall()
            return [{
                "title": row["title"] or "Untitled",
                "code": row["code"],
                "uploaded_at": row["uploaded_at"].isoformat() if row["uploaded_at"] else None,
                "destination": row["destination"] or "unknown",
            } for row in rows]
        except Exception as exc:
            raise ProcessedStoreError(f"Neon recent-history query failed ({type(exc).__name__}).") from exc


def create_processed_store():
    """Use Neon when DATABASE_URL is configured; retain legacy storage otherwise."""
    if os.getenv("DATABASE_URL", "").strip():
        return NeonProcessedStore()
    from app.storage.processed import ProcessedStore
    logger.warning("DATABASE_URL is unset; using legacy ProcessedStore backend.")
    return ProcessedStore()
