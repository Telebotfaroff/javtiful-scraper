import math
import os
import subprocess
from pathlib import Path

from pyrogram import Client
from app.storage.cleanup import cleanup

TELEGRAM_LIMIT = 2_000_000_000


class TelegramUploader:
    name = "telegram"

    def __init__(self, api_id=None, api_hash=None, session="javdl", bot_token=None):
        self.app = Client(session, api_id=int(api_id or os.environ["TELEGRAM_API_ID"]), api_hash=api_hash or os.environ["TELEGRAM_API_HASH"], bot_token=bot_token or os.getenv("TELEGRAM_BOT_TOKEN"))

    @staticmethod
    def _duration(path: Path) -> float:
        value = subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)], text=True).strip()
        return float(value)

    @classmethod
    def split_if_needed(cls, file_path, limit=TELEGRAM_LIMIT):
        path = Path(file_path)
        if path.stat().st_size <= limit: return [str(path)]
        duration = cls._duration(path)
        part_count = math.ceil(path.stat().st_size / limit)
        segment = (duration / part_count) * 0.96
        parts = []
        for index in range(part_count):
            start = index * segment
            length = max(0.1, duration - start) if index == part_count - 1 else segment
            target = path.with_name(f"{path.stem}.part{index + 1}{path.suffix}")
            subprocess.run(["ffmpeg","-y","-ss",str(start),"-i",str(path),"-t",str(length),"-c","copy",str(target)], check=True)
            parts.append(str(target))
        return parts

    def upload(self, file_path, chat_id, caption="", thumbnail=None, duration=None, progress=None):
        paths = self.split_if_needed(file_path)
        results = []
        with self.app:
            for index, path in enumerate(paths, 1):
                part_caption = caption if len(paths) == 1 else f"{caption}\n\n📦 Part {index}/{len(paths)}"
                thumb = thumbnail if thumbnail and not str(thumbnail).startswith(("http://","https://")) else None
                results.append(self.app.send_video(chat_id, path, caption=part_caption, thumb=thumb, duration=int(duration or 0), supports_streaming=True, progress=self._progress(progress)))
        cleanup([path for path in paths if Path(path) != Path(file_path)])
        return results

    @staticmethod
    def _progress(callback):
        if not callback: return None
        def cb(current, total): callback(current, total, "telegram_upload")
        return cb