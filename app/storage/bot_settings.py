"""Small persistent settings store for the bot's optional Telegram channel."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import requests
import psycopg


class BotSettings:
    def __init__(self):
        self.database_url = os.getenv("DATABASE_URL", "").strip()
        self.repo = os.getenv("GITHUB_REPOSITORY", "").strip()
        self.branch = os.getenv("BOT_SETTINGS_BRANCH", "javdl").strip()
        self.path = os.getenv("BOT_SETTINGS_PATH", "database/bot_settings.json").strip().strip("/")
        self.token = (os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
        self.local_path = Path(self.path)
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "JAVDL-BotSettings",
        })
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

    @property
    def api_url(self):
        if not self.repo:
            raise RuntimeError("GITHUB_REPOSITORY is not configured for persistent bot settings.")
        return f"https://api.github.com/repos/{self.repo}/contents/{self.path}"

    def _load(self):
        if self.token:
            response = self.session.get(self.api_url, params={"ref": self.branch}, timeout=20)
            if response.status_code == 404:
                return {"schema_version": 1, "telegram_channel": None}, None
            response.raise_for_status()
            payload = response.json()
            data = json.loads(base64.b64decode(payload.get("content", "")).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Bot settings must be a JSON object.")
            return data, payload.get("sha")

        if not self.local_path.exists():
            return {"schema_version": 1, "telegram_channel": None}, None
        data = json.loads(self.local_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Bot settings must be a JSON object.")
        return data, None

    def _neon_connection(self):
        return psycopg.connect(self.database_url, connect_timeout=10)

    def _ensure_neon_settings(self):
        with self._neon_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS javdl_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

    def get_channel(self):
        if self.database_url:
            self._ensure_neon_settings()
            with self._neon_connection() as conn:
                row = conn.execute(
                    "SELECT setting_value FROM javdl_settings WHERE setting_key = 'telegram_channel'"
                ).fetchone()
            value = row[0] if row and row[0] else os.getenv("TELEGRAM_POST_CHANNEL_ID", "").strip()
        else:
            data, _ = self._load()
            value = data.get("telegram_channel") or os.getenv("TELEGRAM_POST_CHANNEL_ID", "").strip()
        return str(value).strip() if value else None

    def set_channel(self, channel):
        if self.database_url:
            self._ensure_neon_settings()
            with self._neon_connection() as conn:
                conn.execute("""
                    INSERT INTO javdl_settings (setting_key, setting_value, updated_at)
                    VALUES ('telegram_channel', %s, NOW())
                    ON CONFLICT (setting_key) DO UPDATE SET
                        setting_value = EXCLUDED.setting_value, updated_at = NOW()
                """, (str(channel).strip(),))
            return
        data, sha = self._load()
        data["schema_version"] = 1
        data["telegram_channel"] = channel
        encoded = base64.b64encode(
            (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        ).decode("ascii")
        if self.token:
            body = {
                "message": "Configure JAVDL Telegram upload channel",
                "content": encoded,
                "branch": self.branch,
            }
            if sha:
                body["sha"] = sha
            response = self.session.put(self.api_url, json=body, timeout=20)
            response.raise_for_status()
        else:
            self.local_path.parent.mkdir(parents=True, exist_ok=True)
            self.local_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    def clear_channel(self):
        if self.database_url:
            self._ensure_neon_settings()
            with self._neon_connection() as conn:
                conn.execute("""
                    INSERT INTO javdl_settings (setting_key, setting_value, updated_at)
                    VALUES ('telegram_channel', NULL, NOW())
                    ON CONFLICT (setting_key) DO UPDATE SET
                        setting_value = NULL, updated_at = NOW()
                """)
            return
        data, sha = self._load()
        data["schema_version"] = 1
        data["telegram_channel"] = None
        encoded = base64.b64encode(
            (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        ).decode("ascii")
        if self.token:
            body = {
                "message": "Remove JAVDL Telegram upload channel",
                "content": encoded,
                "branch": self.branch,
            }
            if sha:
                body["sha"] = sha
            response = self.session.put(self.api_url, json=body, timeout=20)
            response.raise_for_status()
        else:
            self.local_path.parent.mkdir(parents=True, exist_ok=True)
            self.local_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
