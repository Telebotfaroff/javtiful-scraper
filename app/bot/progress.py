import time


class TelegramProgress:
    def __init__(self, message, min_interval=2.0):
        self.message = message
        self.min_interval = min_interval
        self.last = 0

    async def update(self, current, total, stage):
        try:
            current = float(current or 0)
            total = float(total or 0)
        except (TypeError, ValueError):
            return

        now = time.monotonic()
        if now - self.last < self.min_interval and current < total:
            return

        self.last = now
        pct = (current / total * 100) if total else 0
        if total:
            text = (
                f"{str(stage).title()}\n"
                f"{pct:.1f}%\n"
                f"{current / 1024 / 1024:.1f} MB / "
                f"{total / 1024 / 1024:.1f} MB"
            )
        else:
            text = f"{str(stage).title()}\n{current / 1024 / 1024:.1f} MB"

        await self.message.edit_text(text)
