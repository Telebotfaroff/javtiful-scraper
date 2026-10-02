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
from app.extractor.channel import JavtifulChannelExtractor


extractor = JavtifulExtractor()
channel_extractor = JavtifulChannelExtractor()
uploads = UploadManager()
telegram_uploader = uploads.get("telegram")
pipeline = Pipeline(extractor=extractor, uploaders={"telegram": telegram_uploader, "gofile": uploads.get("gofile")})
pending = {}



def _channel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬇️ Download Page", callback_data="channel|download")]
    ])


async def _run_channel_page(message, state, page_number):
    channel_url = state["url"]
    channel_name = state.get("channel_name", "Channel")
    total_pages = int(state.get("total_pages") or 1)
    status = await message.reply_text(
        f"⏳ Loading page {page_number} ({page_number + 1}/{total_pages})…"
    )

    try:
        page_data = await asyncio.to_thread(
            channel_extractor.page, channel_url, page_number
        )
        items = page_data.get("items", [])
        if not items:
            await status.edit_text(
                f"❌ No videos found on page {page_number}.\n\n"
                f"Channel: {channel_name}"
            )
            return

        await status.edit_text(
            f"📥 Downloading **{len(items)} videos** from page {page_number}…\n\n"
            f"Channel: {channel_name}"
        )

        completed = 0
        failed = 0

        for item in items:
            title = item.get("title") or "Video"
            code = item.get("code")
            caption = f"{code} {title}" if code else title

            if item.get("thumbnail"):
                await asyncio.to_thread(
                    telegram_uploader.send_preview,
                    message.chat.id,
                    item["thumbnail"],
                    title,
                    item.get("post_url"),
                )

            job = Job(
                id=f"TG-CH-{uuid.uuid4().hex[:10]}",
                url=item["post_url"],
                quality="720p",
                uploader="telegram",
                target=message.chat.id,
                caption=caption,
            )

            try:
                await asyncio.to_thread(pipeline.run, job, None)
                completed += 1
            except Exception as exc:
                failed += 1
                await status.edit_text(
                    f"📥 **Channel:** {channel_name}\n"
                    f"📄 **Page:** {page_number}\n"
                    f"🎬 **Progress:** {completed + failed}/{len(items)}\n"
                    f"✅ **Completed:** {completed}\n"
                    f"❌ **Failed:** {failed}\n\n"
                    f"❌ {title}\n{type(exc).__name__}: {exc}"
                )
                continue

            await status.edit_text(
                f"📥 **Channel:** {channel_name}\n"
                f"📄 **Page:** {page_number}\n"
                f"🎬 **Progress:** {completed + failed}/{len(items)}\n"
                f"✅ **Completed:** {completed}\n"
                f"❌ **Failed:** {failed}\n\n"
                f"▶️ {title}"
            )

        await status.edit_text(
            f"✅ **Page {page_number} complete**\n\n"
            f"📺 **Channel:** {channel_name}\n"
            f"🎬 **Videos:** {len(items)}\n"
            f"✅ **Uploaded:** {completed}\n"
            f"❌ **Failed:** {failed}"
        )
    except Exception as exc:
        await status.edit_text(
            f"❌ Channel page download failed\n\n{type(exc).__name__}: {exc}"
        )


def _destination_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📱 Telegram", callback_data="dest|telegram"),
            InlineKeyboardButton("☁️ GoFile", callback_data="dest|gofile"),
        ]
    ])


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
    destination = state.get("destination", "telegram")
    target = message.chat.id if destination == "telegram" else None
    job = Job(
        id=f"TG-{uuid.uuid4().hex[:10]}",
        url=state["url"],
        quality=state["quality"],
        uploader=destination,
        target=target,
        clips=state.get("clips"),
    )
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
        destination_name = "Telegram" if destination == "telegram" else "GoFile"
        lines = [
            "✅ **Upload Complete**",
            "",
            f"🎬 **{title}**",
            f"🎚 **Quality:** {quality}",
            f"⏱ **Duration:** {duration_text}",
            f"📦 **Files:** {len(results)} {upload_word}",
            f"✂️ **Mode:** {mode.title()}",
            f"📤 **Destination:** {destination_name}",
        ]

        if destination == "gofile":
            links = [
                item.get("download_url")
                for item in results
                if isinstance(item, dict) and item.get("download_url")
            ]
            if links:
                lines.extend(["", "🔗 **Download:**", *links])

        lines.extend(["", "✨ Your video is ready!"])
        await status.edit_text("\n".join(lines))
    except Exception as exc:
        await status.edit_text(f"❌ Pipeline failed\n\n{type(exc).__name__}: {exc}")


def register_handlers(app: Client):
    @app.on_message(filters.private & filters.text)
    async def link_handler(client, message):
        text = message.text.strip()
        state = pending.get(message.from_user.id)

        if state and state.get("channel_waiting_page"):
            if not re.fullmatch(r"\d+", text):
                return await message.reply_text("Invalid page number. Use 0 for the first page.")
            page_number = int(text)
            total_pages = int(state.get("total_pages") or 0)
            if page_number < 0 or page_number >= total_pages:
                return await message.reply_text(
                    f"Invalid page. Enter a number from 0 to {max(0, total_pages - 1)}."
                )
            state.pop("channel_waiting_page", None)
            await _run_channel_page(message, state, page_number)
            pending.pop(message.from_user.id, None)
            return

        if state and state.get("clip_waiting"):
            match = re.fullmatch(r"\s*([^\-]+)\s*-\s*([^\-]+)\s*", text)
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
            try:
                await _run_job(message, state)
            finally:
                pending.pop(message.from_user.id, None)
            return

        if text.startswith("/start"):
            return await message.reply_text("JAVDL test bot is ready.\n\nSend a supported Javtiful URL to begin.")
        if not text.startswith(("https://javtiful.com/","http://javtiful.com/")):
            return await message.reply_text("Send a supported Javtiful URL.")

        if re.fullmatch(r"https?://javtiful\.com/channel/[^/?#]+/?(?:\?.*)?", text, re.I):
            status = await message.reply_text("🔎 Inspecting channel…")
            try:
                info = await asyncio.to_thread(channel_extractor.inspect, text)
                total_pages = int(info.get("total_pages") or 1)
                total_videos = info.get("total_videos")
                total_videos_text = str(total_videos) if total_videos is not None else "Unknown"
                pending[message.from_user.id] = {
                    "type": "channel",
                    "url": text,
                    "channel_name": info.get("channel_name") or "Channel",
                    "total_videos": total_videos,
                    "total_pages": total_pages,
                }
                await status.edit_text(
                    f"📺 **Channel:** {info.get('channel_name') or 'Channel'}\n"
                    f"🎬 **Total videos:** {total_videos_text}\n"
                    f"📄 **Total pages:** {total_pages}\n\n"
                    "Choose an option:",
                    reply_markup=_channel_keyboard(),
                )
            except Exception as exc:
                await status.edit_text(
                    f"❌ Channel extraction failed\n\n{type(exc).__name__}: {exc}"
                )
            return
        status = await message.reply_text("🔎 Extracting video information…")
        try:
            video = extractor.extract(text)
            if not video.qualities:
                return await status.edit_text("❌ No downloadable source/quality was exposed by the page.")
            pending[message.from_user.id] = {"url": text, "quality": "720p"}
            title = video.title or "Video"
            duration = video.duration or "unknown"

            # Show the post preview immediately after extraction, before the
            # user chooses quality/download mode.
            preview = await asyncio.to_thread(
                telegram_uploader.send_preview,
                message.chat.id,
                video.thumbnail,
                title,
                video.source_url or text,
            )
            await status.edit_text(
                f"🎬 {title}\n\n⏱ Duration: {duration}\n\n"
                + ("🖼 Preview uploaded.\n\n" if preview else "")
                + "Quality: 720p\n\nChoose upload destination:",
                reply_markup=_destination_keyboard(),
            )
        except Exception as exc:
            await status.edit_text(f"❌ Extraction failed\n\n{type(exc).__name__}: {exc}")


    @app.on_callback_query(filters.regex(r"^channel\|download$"))
    async def channel_download_handler(client, query):
        state = pending.get(query.from_user.id)
        if not state or state.get("type") != "channel":
            return await query.answer("Session expired. Send the channel URL again.", show_alert=True)

        state["channel_waiting_page"] = True
        await query.answer("Choose a page")
        total_pages = int(state.get("total_pages") or 1)
        await query.message.edit_text(
            f"📺 **{state.get('channel_name', 'Channel')}**\n\n"
            f"Enter page number from **0** to **{total_pages - 1}**.\n"
            "0 = website page 1\n"
            "1 = website page 2\n"
            "2 = website page 3\n\n"
            "Send only the page number."
        )


    @app.on_callback_query(filters.regex(r"^dest\|"))
    async def destination_handler(client, query):
        state = pending.get(query.from_user.id)
        if not state:
            return await query.answer("Session expired. Send the URL again.", show_alert=True)

        destination = query.data.split("|", 1)[1]
        if destination not in {"telegram", "gofile"}:
            return await query.answer("Invalid destination.", show_alert=True)

        state["destination"] = destination
        label = "Telegram" if destination == "telegram" else "GoFile"
        await query.answer(f"Destination: {label}")
        await query.message.edit_text(
            f"🎚 Quality: 720p\n"
            f"📤 Destination: {label}\n\n"
            "Choose download mode:",
            reply_markup=_mode_keyboard(),
        )


    @app.on_callback_query(filters.regex(r"^mode\|"))
    async def mode_handler(client, query):
        state = pending.get(query.from_user.id)
        if not state:
            return await query.answer("Session expired. Send the URL again.", show_alert=True)
        if "destination" not in state:
            return await query.answer("Choose an upload destination first.", show_alert=True)
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

