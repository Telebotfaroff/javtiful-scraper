import asyncio, time
class TelegramProgress:
    def __init__(self, message, min_interval=2.0): self.message=message; self.min_interval=min_interval; self.last=0
    async def update(self,current,total,stage):
        now=time.monotonic()
        if now-self.last < self.min_interval and current < total: return
        self.last=now; pct=(current/total*100) if total else 0
        text=f"{stage.title()}\\n{pct:.1f}%\\n{current/1024/1024:.1f} MB / {total/1024/1024:.1f} MB" if total else f"{stage.title()}\\n{current/1024/1024:.1f} MB"
        await self.message.edit_text(text)
