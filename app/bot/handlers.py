import asyncio
import os
import uuid
import re

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.bot.progress import TelegramProgress, ParallelTelegramProgress
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


def _channel_mode_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🐢 Sequential", callback_data="channel|sequential"),
            InlineKeyboardButton("⚡ Parallel", callback_data="channel|parallel"),
        ]
    ])


def _make_channel_job(item, chat_id):
    title = item.get("title") or "Video"
    code = item.get("code")
    if code and not re.match(rf"^\s*{re.escape(code)}(?:\s|$)", title, re.I):
        caption = f"{code} {title}"
    else:
        caption = title
    return Job(
        id=f"TG-CH-{uuid.uuid4().hex[:10]}",
        url=item["post_url"],
        quality="720p",
        uploader="telegram",
        target=chat_id,
        caption=caption,
    )


async def _run_channel_sequential(message, state, page_number, items, status):
    channel_name = state.get("channel_name", "Channel")
    completed = failed = 0
    for item in items:
        title = item.get("title") or "Video"
        job = _make_channel_job(item, message.chat.id)
        progress = TelegramProgress(status, min_interval=2.0)
        try:
            await status.edit_text(
                f"⬇️ **Downloading:** {title}\n"
                f"📺 **Channel:** {channel_name}\n"
                f"📄 **Page:** {page_number}\n"
                f"🎬 **Video:** {completed + failed + 1}/{len(items)}"
            )
            await asyncio.to_thread(pipeline.run, job, _progress_callback(progress))
            completed += 1
            code = item.get("code") or ""
            await status.reply_text(
                f"✅ **Uploaded successfully to channel**\n\n"
                f"🎬 **{code + ' ' if code else ''}{title}**"
            )
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
    return completed, failed


async def _run_channel_parallel(message, state, page_number, items, status):
    channel_name = state.get("channel_name", "Channel")
    queue = asyncio.Queue(maxsize=max(1, int(os.getenv("TELEGRAM_BATCH_BUFFER", "2"))))
    progress = ParallelTelegramProgress(status, min_interval=5.0)
    progress.set_total(len(items))

    upload_workers = max(1, int(os.getenv("TELEGRAM_BATCH_UPLOAD_WORKERS", "2")))

    async def producer():
        for index, item in enumerate(items):
            title = item.get("title") or "Video"
            job = _make_channel_job(item, message.chat.id)
            try:
                progress.set_download_title(title)
                video = await asyncio.to_thread(
                    pipeline.prepare_download,
                    job,
                    _progress_callback(progress, worker_id=f"download-{index}"),
                )
                progress.mark_download_complete()
                await queue.put(("ok", index, item, job, video))
                progress.set_queue(queue.qsize())
            except Exception as exc:
                await queue.put(("error", index, item, job, exc))
        for _ in range(upload_workers):
            await queue.put(("done",))

    async def consumer(worker_id):
        completed = failed = 0
        while True:
            entry = await queue.get()
            if entry[0] == "done":
                queue.task_done()
                break
            kind, index, item, job, payload = entry
            title = item.get("title") or "Video"
            if kind == "error":
                failed += 1
                progress.mark_failed()
                progress.set_queue(queue.qsize())
                queue.task_done()
                continue
            try:
                progress.set_upload_title(title)
                progress.set_queue(queue.qsize())
                await asyncio.to_thread(
                    pipeline.upload_prepared,
                    job,
                    payload,
                    _progress_callback(progress, worker_id=f"upload-{worker_id}"),
                )
                completed += 1
                progress.mark_upload_complete()
                progress.set_queue(queue.qsize())
                code = item.get("code") or ""
                await status.reply_text(
                    f"✅ **Uploaded successfully to channel**\n\n"
                    f"🎬 **{code + ' ' if code else ''}{title}**"
                )
            except Exception as exc:
                failed += 1
                progress.mark_failed()
                progress.set_queue(queue.qsize())
                await status.edit_text(
                    f"⚡ **Parallel mode**\n"
                    f"📺 **Channel:** {channel_name}\n"
                    f"📄 **Page:** {page_number}\n"
                    f"🎬 **Progress:** {progress.upload_complete + progress.failed}/{len(items)}\n"
                    f"✅ **Uploaded:** {progress.upload_complete}\n"
                    f"❌ **Failed:** {progress.failed}\n\n"
                    f"❌ {title}\n{type(exc).__name__}: {exc}"
                )
            finally:
                queue.task_done()
        return completed, failed

    producer_task = asyncio.create_task(producer())
    consumer_tasks = [
        asyncio.create_task(consumer(index + 1))
        for index in range(upload_workers)
    ]
    try:
        await asyncio.gather(producer_task, *consumer_tasks)
    except Exception:
        producer_task.cancel()
        for task in consumer_tasks:
            task.cancel()
        await asyncio.gather(
            producer_task,
            *consumer_tasks,
            return_exceptions=True,
        )
        raise

    totals = [task.result() for task in consumer_tasks]
    return sum(x[0] for x in totals), sum(x[1] for x in totals)


async def _run_channel_page(message, state, page_number, parallel=False):
    channel_url = state["url"]
    channel_name = state.get("channel_name", "Channel")
    total_pages = int(state.get("total_pages") or 1)
    status = await message.reply_text(
        f"⏳ Loading page {page_number} ({page_number + 1}/{total_pages})…"
    )
    try:
        page_data = await asyncio.to_thread(channel_extractor.page, channel_url, page_number)
        items = page_data.get("items", [])
        if not items:
            await status.edit_text(
                f"❌ No videos found on page {page_number}.\n\nChannel: {channel_name}"
            )
            return
        mode_name = "Parallel" if parallel else "Sequential"
        await status.edit_text(
            f"📥 **{mode_name} mode**\n"
            f"📺 **Channel:** {channel_name}\n"
            f"📄 **Page:** {page_number}\n"
            f"🎬 **Videos:** {len(items)}"
        )
        if parallel:
            completed, failed = await _run_channel_parallel(message, state, page_number, items, status)
        else:
            completed, failed = await _run_channel_sequential(message, state, page_number, items, status)
        await status.edit_text(
            f"✅ **Page {page_number} complete**\n\n"
            f"📺 **Channel:** {channel_name}\n"
            f"🎬 **Videos:** {len(items)}\n"
            f"⚡ **Mode:** {mode_name}\n"
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
            InlineKeyboardButton("📢 Channel", callback_data="dest|telegram_channel"),
        ],
        [
            InlineKeyboardButton("☁️ GoFile", callback_data="dest|gofile"),
        ],
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


def _progress_callback(progress_obj, worker_id=None):
    loop = asyncio.get_running_loop()
    def callback(current, total, stage):
        if worker_id is not None and str(stage).startswith("telegram_upload"):
            stage = f"telegram_upload:{worker_id}"
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(progress_obj.update(current, total, stage))
        )
    return callback


async def _run_job(message, state):
    status = await message.reply_text("⏳ Starting download…")
    progress = TelegramProgress(status)
    destination = state.get("destination", "telegram")

    if destination == "telegram_channel":
        target = os.getenv("TELEGRAM_POST_CHANNEL_ID", "").strip()
        if not target:
            await status.edit_text(
                "❌ Channel posting is not configured.\n\n"
                "Set **TELEGRAM_POST_CHANNEL_ID** to your channel username "
                "(for example `@mychannel`) or numeric channel ID, then restart the bot."
            )
            return
        uploader = "telegram"
    else:
        target = message.chat.id if destination == "telegram" else None
        uploader = destination

    job = Job(
        id=f"TG-{uuid.uuid4().hex[:10]}",
        url=state["url"],
        quality=state["quality"],
        uploader=uploader,
        target=target,
        clips=state.get("clips"),
        caption=state.get("caption"),
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
        destination_name = (
            "Telegram Channel" if destination == "telegram_channel"
            else ("Telegram" if destination == "telegram" else "GoFile")
        )
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
            state["channel_page"] = page_number
            state.pop("channel_waiting_page", None)
            state["channel_waiting_mode"] = True
            return await message.reply_text(
                f"📄 Page **{page_number}** selected.\n\nChoose download mode:",
                reply_markup=_channel_mode_keyboard(),
            )

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

            await status.edit_text(
                f"🎬 {title}\n\n"
                f"⏱ Duration: {duration}\n\n"
                "🖼 Thumbnail will be uploaded with the video.\n\n"
                "Quality: 720p\n\nChoose upload destination:",
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


    @app.on_callback_query(filters.regex(r"^channel\|(sequential|parallel)$"))
    async def channel_mode_handler(client, query):
        state = pending.get(query.from_user.id)
        if not state or state.get("type") != "channel":
            return await query.answer("Session expired. Send the channel URL again.", show_alert=True)
        if not state.get("channel_waiting_mode"):
            return await query.answer("Choose the page first.", show_alert=True)

        mode = query.data.split("|", 1)[1]
        page_number = int(state["channel_page"])
        state.pop("channel_waiting_mode", None)
        state.pop("channel_page", None)
        await query.answer("Starting " + mode + " mode")
        try:
            await _run_channel_page(
                query.message,
                state,
                page_number,
                parallel=(mode == "parallel"),
            )
        finally:
            pending.pop(query.from_user.id, None)


    @app.on_callback_query(filters.regex(r"^dest\|"))
    async def destination_handler(client, query):
        state = pending.get(query.from_user.id)
        if not state:
            return await query.answer("Session expired. Send the URL again.", show_alert=True)

        destination = query.data.split("|", 1)[1]
        if destination not in {"telegram", "telegram_channel", "gofile"}:
            return await query.answer("Invalid destination.", show_alert=True)

        if destination == "telegram_channel":
            channel_id = os.getenv("TELEGRAM_POST_CHANNEL_ID", "").strip()
            if not channel_id:
                return await query.answer(
                    "Channel posting is not configured. Set TELEGRAM_POST_CHANNEL_ID.",
                    show_alert=True,
                )

        state["destination"] = destination
        label = (
            "Telegram Channel" if destination == "telegram_channel"
            else ("Telegram" if destination == "telegram" else "GoFile")
        )
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

