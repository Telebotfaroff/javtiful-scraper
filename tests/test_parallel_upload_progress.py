import asyncio

from app.bot.progress import ParallelTelegramProgress


class FakeMessage:
    def __init__(self):
        self.edits = []

    async def edit_text(self, text):
        self.edits.append(text)


def test_parallel_upload_progress_keeps_each_video_size_separate():
    async def scenario():
        message = FakeMessage()
        progress = ParallelTelegramProgress(message, min_interval=60)
        first_id = "video-0"
        second_id = "video-1"

        progress.set_upload_title("First video", upload_id=first_id)
        progress.set_upload_title("Second video", upload_id=second_id)
        await progress.update(1.5 * 1024**3, 1.6 * 1024**3, f"telegram_upload:{first_id}")
        await progress.update(1.4 * 1024**3, 1.5 * 1024**3, f"telegram_upload:{second_id}")

        rendered = progress._render()
        assert "Title - First video" in rendered
        assert "Title - Second video" in rendered
        assert "1.5 GB / 1.6 GB" in rendered
        assert "1.4 GB / 1.5 GB" in rendered
        assert "2.9 GB" not in rendered

        progress.mark_upload_complete(upload_id=first_id)
        rendered = progress._render()
        assert "Title - First video" not in rendered
        assert "Title - Second video" in rendered
        assert "Upload complete - 1" in rendered
        await progress.close()

    asyncio.run(scenario())
