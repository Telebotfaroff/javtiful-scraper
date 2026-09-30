from pyrogram import Client, filters
from app.extractor.javtiful import JavtifulExtractor

extractor=JavtifulExtractor()
def register_handlers(app: Client):
    @app.on_message(filters.private & filters.text)
    async def link_handler(client,message):
        url=message.text.strip()
        if not url.startswith(("https://javtiful.com/","http://javtiful.com/")):
            return await message.reply_text("Send a supported Javtiful URL.")
        status=await message.reply_text("🔎 Extracting video information…")
        try:
            video=extractor.extract(url)
            qualities=", ".join(video.qualities) or "none exposed"
            await status.edit_text(f"🎬 {video.title or 'Video'}\n\nAvailable quality: {qualities}\n\nDownloader/upload pipeline ready.")
        except Exception as exc:
            await status.edit_text(f"❌ Extraction failed: {exc}")
