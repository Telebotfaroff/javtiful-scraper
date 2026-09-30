import time


class TelegramProgress:
    def __init__(self, message, min_interval=2.0):
        self.message = message
        self.min_interval = min_interval
        self.last = 0.0
        self.last_current = 0.0
        self.last_time = time.monotonic()

    @staticmethod
    def _bar(percent, width=14):
        filled = round(width * percent / 100)
        return "▰" * filled + "▱" * (width - filled)

    @staticmethod
    def _size(value):
        value = float(value)
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
        remaining = max(0, total - current)
        seconds = int(remaining / speed)
        if seconds >= 3600:
            return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"
        if seconds >= 60:
            return f"{seconds // 60}m {seconds % 60:02d}s"
        return f"{seconds}s"

    async def update(self, current, total, stage):
        try:
            current = float(current or 0)
            total = float(total or 0)
        except (TypeError, ValueError):
            return

        now = time.monotonic()

        # Throttle Telegram edits, but always allow completion.
        if (
            now - self.last < self.min_interval
            and (not total or current < total)
        ):
            return

        elapsed = now - self.last_time
        delta = current - self.last_current
        speed = delta / elapsed if elapsed > 0 and delta >= 0 else 0

        self.last = now
        self.last_time = now
        self.last_current = current

        name = str(stage).replace("_", " ").title()

        if total > 0:
            percent = min(100.0, max(0.0, current / total * 100))
            bar = self._bar(percent)
            text = (
                f"{name}\n\n"
                f"{bar} {percent:.1f}%\n"
                f"📦 {self._size(current)} / {self._size(total)}\n"
                f"⚡ {self._speed(speed)}  •  ⏳ {self._eta(current, total, speed)}"
            )
        else:
            text = (
                f"{name}\n\n"
                f"📦 {self._size(current)}\n"
                f"⚡ {self._speed(speed)}"
            )

        await self.message.edit_text(text)
