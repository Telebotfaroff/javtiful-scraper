import asyncio
import uuid
import re

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.bot.progress import TelegramProgress
from app.jobs.pipeline import Pipeline
from app.jobs.queue import Job
from app.uploaders.manager import UploadManager
from app.extractor.javtiful import JavtifulExtractor


extractor = JavtifulExtractor()
uploads = UploadManager()
pipeline = Pipeline(extractor=extractor, uploaders={"telegram": uploads.get("telegram"), "gofile": uploads.get("gofile")})
pending = {}


def _quality_keyboard(qualities):
    buttons = [InlineKeyboardButton(str(q), callback_data=f"q|{q}") for q in qualities]
    buttons.append(InlineKeyboardButton("Best available", callback_data="q|best"))
    return InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])


def _mode_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬇️ Download Full Video", callback_data="mode|full"), InlineKeyboardButton("✂️ Download Clip", callback_data="mode|clip")]])


def _valid_time(value):
    return bool(re.fullmatch(r"(?:[0-9]+(?::[0-5][0-9]){0,2})", value.strip()))


def _seconds(value):
    parts = [int(x) for x in value.split(":")]
    if len(parts) == 1: return parts[0]
    if len(parts) == 2: return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def _progress_callback(progress_obj):
    loop = asyncio.get_running_loop()
    def callback(current, total, stage):
        loop.call_soon_threadsafe(lambda: asyncio.create_task(progress_obj.update(current, total, stage)))
    return callback


async def _run_job(message, state):
    status = await message.reply_text("⏳ Starting download…")
    progress = TelegramProgress(status)
    job = Job(id=f"TG-{uuid.uuid4().hex[:10]}", url=state["url"], quality=state["quality"], uploader="telegram", target=message.chat.id, clips=state.get("clips"))
    try:
        video, results = await asyncio.to_thread(pipeline.run, job, _progress_callback(progress))
        mode = "clip" if state.get("clips") else "full"
        quality = video.selected_quality or state["quality"]
        title = video.title or "Video"
        duration = video.duration
        if duration:
            duration = int(duration)
            hours, remainder = divmod(duration, 3600)
            minutes, seconds = divmod(remainder, 60)
            duration_text = (
                f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                if hours else f"{minutes:02d}:{seconds:02d}"
            )
        else:
            duration_text = "Unknown"

        upload_word = "upload" if len(results) == 1 else "uploads"
        await status.edit_text(
            f"✅ **Upload Complete**\n\n"
            f"🎬 **{title}**\n"
            f"🎚 **Quality:** {quality}\n"
            f"⏱ **Duration:** {duration_text}\n"
            f"📦 **Files:** {len(results)} {upload_word}\n"
            f"✂️ **Mode:** {mode.title()}\n"
            f"📤 **Destination:** Telegram\n\n"
            f"✨ Your video is ready!"
        )
    except Exception as exc:
        await status.edit_text(f"❌ Pipeline failed\n\n{type(exc).__name__}: {exc}")


def register_handlers(app: Client):
    @app.on_message(filters.private & filters.text)
    async def link_handler(client, message):
        text = message.text.strip()
        if text.startswith("/start"):
            return await message.reply_text("JAVDL test bot is ready.\n\nSend a supported Javtiful URL to begin.")
        if not text.startswith(("https://javtiful.com/","http://javtiful.com/")):
            return await message.reply_text("Send a supported Javtiful URL.")
        status = await message.reply_text("🔎 Extracting video information…")
        try:
            video = extractor.extract(text)
            if not video.qualities:
                return await status.edit_text("❌ No downloadable source/quality was exposed by the page.")
            pending[message.from_user.id] = {"url": text, "qualities": list(video.qualities)}
            title = video.title or "Video"
            duration = video.duration or "unknown"
            await status.edit_text(f"🎬 {title}\n\n⏱ Duration: {duration}\nChoose a quality:", reply_markup=_quality_keyboard(video.qualities))
        except Exception as exc:
            await status.edit_text(f"❌ Extraction failed\n\n{type(exc).__name__}: {exc}")


    @app.on_callback_query(filters.regex(r"^q\|"))
    async def quality_handler(client, query):
        state = pending.get(query.from_user.id)
        if not state:
            return await query.answer("Session expired. Send the URL again.", show_alert=True)
        quality = query.data.split("|",1)[1]
        state["quality"] = quality
        await query.answer(f"Quality: {quality}")
        await query.message.edit_text(f"🎚 Quality: {quality}\n\nChoose upload mode:", reply_markup=_mode_keyboard())


    @app.on_callback_query(filters.regex(r"^mode\|"))
    async def mode_handler(client, query):
        state = pending.get(query.from_user.id)
        if not state or "quality" not in state:
            return await query.answer("Choose a quality first.", show_alert=True)
        mode = query.data.split("|",1)[1]
        if mode == "full":
            state.pop("clips", None)
            await query.answer("Full video selected")
            await query.message.edit_text("▶️ Full video selected. Starting pipeline…")
            await _run_job(query.message, state)
            pending.pop(query.from_user.id, None)
            return
        state["clip_waiting"] = True
        await query.answer("Clip mode selected")
        await query.message.edit_text("✂️ Send one clip range like 00:00-01:30. You can use SS, MM:SS, or HH:MM:SS.")


    @app.on_message(filters.private & filters.text)
    async def clip_handler(client, message):
        state = pending.get(message.from_user.id)
        if not state or not state.get("clip_waiting"):
            return
        match = re.fullmatch(r"\s*([^\-]+)\s*-\s*([^\-]+)\s*", message.text)
        if not match:
            return await message.reply_text("Invalid range. Use 00:00-01:30.")
        start, end = match.group(1).strip(), match.group(2).strip()
        if not (_valid_time(start) and _valid_time(end)):
            return await message.reply_text("Invalid time. Use SS, MM:SS, or HH:MM:SS.")
        if _seconds(end) <= _seconds(start):
            return await message.reply_text("End time must be after start time.")
        state["clips"] = [(start, end)]
        state.pop("clip_waiting", None)
        await message.reply_text("✂️ Clip selected. Starting pipeline…")
        await _run_job(message, state)
        pending.pop(message.from_user.id, None)