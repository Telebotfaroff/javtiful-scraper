import asyncio
import time


class TelegramProgress:
    def __init__(self, message, min_interval=5.0):
        self.message = message
        self.min_interval = min_interval
        self.last = 0.0
        self.last_current = 0.0
        self.last_time = time.monotonic()
        self.speed_ema = 0.0
        self.stage = None
        self.title = "Video"
        self._lock = asyncio.Lock()
        self._pending = None
        self._worker = None
        self._closed = False

    def set_title(self, title):
        self.title = title or "Video"

    @staticmethod
    def _bar(percent, width=14):
        filled = round(width * percent / 100)
        return "▰" * filled + "▱" * (width - filled)

    @staticmethod
    def _size(value):
        value = float(value or 0)
        units = ("B", "KB", "MB", "GB", "TB")
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} TB"

    @staticmethod
    def _speed(bytes_per_second):
        if bytes_per_second <= 0:
            return "—"
        return f"{TelegramProgress._size(bytes_per_second)}/s"

    @staticmethod
    def _eta(current, total, speed):
        if total <= 0 or speed <= 0:
            return "—"
        seconds = int(max(0, total - current) / speed)
        if seconds >= 3600:
            return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"
        if seconds >= 60:
            return f"{seconds // 60}m {seconds % 60:02d}s"
        return f"{seconds}s"

    def _render(self, current, total, stage):
        now = time.monotonic()
        if stage != self.stage:
            self.stage = stage
            self.last_current = current
            self.last_time = now
            self.speed_ema = 0.0

        elapsed = now - self.last_time
        delta = current - self.last_current
        instant_speed = delta / elapsed if elapsed > 0 and delta >= 0 else 0
        if instant_speed > 0:
            self.speed_ema = (self.speed_ema * 0.75) + (instant_speed * 0.25)
        self.last_time = now
        self.last_current = current

        if total > 0:
            percent = min(100.0, max(0.0, current / total * 100))
            return (
                f"⬇️ **Downloading**\n"
                f"Title - {self.title}\n"
                f"{self._bar(percent)} {percent:.1f}%\n"
                f"📦 {self._size(current)} / {self._size(total)}\n"
                f"⚡ {self._speed(self.speed_ema)}  •  ⏳ {self._eta(current, total, self.speed_ema)}"
            )
        return (
            f"⬇️ **Downloading**\n"
            f"Title - {self.title}\n"
            f"📦 {self._size(current)}\n"
            f"⚡ {self._speed(self.speed_ema)}"
        )

    async def _send_loop(self):
        while not self._closed:
            await asyncio.sleep(self.min_interval)
            async with self._lock:
                pending = self._pending
                self._pending = None
            if pending is None:
                continue
            try:
                await self.message.edit_text(self._render(*pending))
            except Exception:
                continue

    async def update(self, current, total, stage):
        try:
            current = float(current or 0)
            total = float(total or 0)
        except (TypeError, ValueError):
            return

        async with self._lock:
            self._pending = (current, total, stage)
            if self._worker is None or self._worker.done():
                self._worker = asyncio.create_task(self._send_loop())

    async def close(self):
        self._closed = True
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)


class ParallelTelegramProgress:
    """Render download and upload progress together for batch mode."""

    def __init__(self, message, min_interval=5.0):
        self.message = message
        self.min_interval = min_interval
        self.last = 0.0
        self.download = {"current": 0.0, "total": 0.0, "time": time.monotonic(), "last": 0.0, "speed": 0.0}
        self.upload = {"current": 0.0, "total": 0.0, "time": time.monotonic(), "last": 0.0, "speed": 0.0}
        self.download_title = "Video"
        self.upload_title = "Video"
        self.download_complete = 0
        self.upload_complete = 0
        self.failed = 0
        self.queue = 0
        self.total_jobs = 0
        self._lock = asyncio.Lock()
        self._pending = None
        self._worker = None
        self._closed = False

    def set_total(self, total):
        self.total_jobs = int(total or 0)

    def set_download_title(self, title):
        self.download_title = title or "Video"

    def set_upload_title(self, title):
        self.upload_title = title or "Video"

    def set_queue(self, count):
        self.queue = max(0, int(count or 0))

    def mark_download_complete(self):
        self.download_complete += 1

    def mark_upload_complete(self):
        self.upload_complete += 1

    def mark_failed(self):
        self.failed += 1

    @staticmethod
    def _bar(percent, width=14):
        filled = round(width * percent / 100)
        return "▰" * filled + "▱" * (width - filled)

    @staticmethod
    def _size(value):
        value = float(value or 0)
        units = ("B", "KB", "MB", "GB", "TB")
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} TB"

    @classmethod
    def _speed(cls, value):
        return "—" if value <= 0 else f"{cls._size(value)}/s"

    @classmethod
    def _eta(cls, current, total, speed):
        if total <= 0 or speed <= 0:
            return "—"
        seconds = int(max(0, total - current) / speed)
        if seconds >= 3600:
            return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"
        if seconds >= 60:
            return f"{seconds // 60}m {seconds % 60:02d}s"
        return f"{seconds}s"

    def _update_state(self, state, current, total):
        now = time.monotonic()
        current = float(current or 0)
        total = float(total or 0)
        elapsed = now - state["time"]
        delta = current - state["last"]
        instant = delta / elapsed if elapsed > 0 and delta >= 0 else 0
        if instant > 0:
            state["speed"] = state["speed"] * 0.75 + instant * 0.25
        state["current"] = current
        state["total"] = total
        state["last"] = current
        state["time"] = now

    def _render(self):
        def section(icon, label, title, state):
            current = state["current"]
            total = state["total"]
            speed = state["speed"]
            if total > 0:
                percent = min(100.0, max(0.0, current / total * 100))
                return (
                    f"{icon} **{label}**\n"
                    f"Title - {title}\n"
                    f"{self._bar(percent)} {percent:.1f}%\n"
                    f"📦 {self._size(current)} / {self._size(total)}\n"
                    f"⚡ {self._speed(speed)}  •  ⏳ {self._eta(current, total, speed)}"
                )
            return (
                f"{icon} **{label}**\n"
                f"Title - {title}\n"
                f"📦 {self._size(current)}\n"
                f"⚡ {self._speed(speed)}"
            )

        counts = (
            f"Download complete - {self.download_complete}\n"
            f"Upload complete - {self.upload_complete}\n"
            f"Queue - {self.queue}"
        )
        return (
            section("⬇️", "Downloading", self.download_title, self.download)
            + "\n\n"
            + section("⬆️", "Uploading", self.upload_title, self.upload)
            + "\n\n"
            + counts
        )

    async def _send_loop(self):
        while not self._closed:
            await asyncio.sleep(self.min_interval)
            async with self._lock:
                pending = self._pending
                self._pending = None
            if pending is None:
                continue
            try:
                await self.message.edit_text(self._render())
            except Exception:
                continue

    async def update(self, current, total, stage):
        if str(stage).startswith("telegram_upload"):
            self._update_state(self.upload, current, total)
        elif stage not in {"extract", "clip"}:
            self._update_state(self.download, current, total)
        else:
            return

        async with self._lock:
            self._pending = True
            if self._worker is None or self._worker.done():
                self._worker = asyncio.create_task(self._send_loop())

    async def close(self):
        self._closed = True
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
