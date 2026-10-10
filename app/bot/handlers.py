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
from app.storage.processed import ProcessedStore, ProcessedStoreError
from app.storage.bot_settings import BotSettings


extractor = JavtifulExtractor()
channel_extractor = JavtifulChannelExtractor()
processed_store = ProcessedStore()
bot_settings = BotSettings()
uploads = UploadManager()
telegram_uploader = uploads.get("telegram")
pipeline = Pipeline(extractor=extractor, uploaders={"telegram": telegram_uploader, "gofile": uploads.get("gofile")})
pending = {}


async def _reply_and_delete_later(message, text, reply_markup=None, delay=30):
    """Reply to a user's message and remove the reply after a short delay."""
    reply = await message.reply_text(text, reply_markup=reply_markup)
    asyncio.create_task(_delete_message_later(message, delay))
    asyncio.create_task(_delete_message_later(reply, delay))
    return reply


async def _delete_message_later(message, delay=30):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


def _schedule_delete(message, delay=30):
    """Schedule a message for deletion without blocking the handler."""
    asyncio.create_task(_delete_message_later(message, delay))


async def _delete_status_later(message, delay=30):
    await _delete_message_later(message, delay)




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


def _video_code(url, title=None):
    return channel_extractor._extract_code(title or "", url)


def _message_ids(value):
    """Collect Telegram message IDs from nested uploader results."""
    found = []
    if isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_message_ids(item))
    elif isinstance(value, dict):
        for key in ("message_id", "id"):
            item = value.get(key)
            if isinstance(item, int):
                found.append(item)
    else:
        item = getattr(value, "id", None)
        if isinstance(item, int):
            found.append(item)
    return found


def _configured_channel():
    return bot_settings.get_channel()


def _admin_ids():
    return {value.strip() for value in os.getenv("ADMIN_USER_IDS", "").split(",") if value.strip()}


def _is_admin(user_id):
    return str(user_id) in _admin_ids()


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
        target=_configured_channel() or chat_id,
        fallback_target=chat_id if _configured_channel() else None,
        caption=caption,
    )


async def _run_channel_sequential(message, state, page_number, items, status):
    channel_name = state.get("channel_name", "Channel")
    completed = failed = 0
    for item in items:
        title = item.get("title") or "Video"
        job = _make_channel_job(item, message.chat.id)
        progress = TelegramProgress(status, min_interval=2.0)
        code = item.get("code") or _video_code(item.get("post_url"), title)
        if not processed_store.claim(item.get("post_url"), code):
            continue
        try:
            await status.edit_text(
                f"⬇️ **Downloading:** {title}\n"
                f"📺 **Channel:** {channel_name}\n"
                f"📄 **Page:** {page_number}\n"
                f"🎬 **Video:** {completed + failed + 1}/{len(items)}"
            )
            _, upload_results = await asyncio.to_thread(pipeline.run, job, _progress_callback(progress))
            processed_store.mark_completed(
                item.get("post_url"), code, title,
                destination="telegram", message_ids=_message_ids(upload_results),
            )
            completed += 1
            display_code = item.get("code") or ""
            sent = await status.reply_text(
                f"✅ **Uploaded successfully to channel**\n\n"
                f"🎬 **{display_code + ' ' if display_code else ''}{title}**"
            )
            _schedule_delete(sent)
        except Exception as exc:
            processed_store.release(item.get("post_url"), code)
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
            code = item.get("code") or _video_code(item.get("post_url"), title)
            if not processed_store.claim(item.get("post_url"), code):
                await queue.put(("skip", index, item, job, None))
                continue
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
                processed_store.release(item.get("post_url"), code)
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
            if kind == "skip":
                queue.task_done()
                continue
            if kind == "error":
                failed += 1
                progress.mark_failed()
                progress.set_queue(queue.qsize())
                queue.task_done()
                continue
            try:
                progress.set_upload_title(title)
                progress.set_queue(queue.qsize())
                upload_results = await asyncio.to_thread(
                    pipeline.upload_prepared,
                    job,
                    payload,
                    _progress_callback(progress, worker_id=f"upload-{worker_id}"),
                )
                code = item.get("code") or _video_code(item.get("post_url"), title)
                processed_store.mark_completed(
                    item.get("post_url"), code, title,
                    destination="telegram", message_ids=_message_ids(upload_results),
                )
                completed += 1
                progress.mark_upload_complete()
                progress.set_queue(queue.qsize())
                display_code = item.get("code") or ""
                sent = await status.reply_text(
                    f"✅ **Uploaded successfully to channel**\n\n"
                    f"🎬 **{display_code + ' ' if display_code else ''}{title}**"
                )
                _schedule_delete(sent)
            except Exception as exc:
                code = item.get("code") or _video_code(item.get("post_url"), title)
                processed_store.release(item.get("post_url"), code)
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


async def _run_channel_page(message, state, page_number, requested_count, parallel=False):
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
            await _delete_status_later(status)
            return

        already_completed = 0
        remaining = []
        for item in items:
            code = item.get("code") or _video_code(item.get("post_url"), item.get("title"))
            if processed_store.is_completed(item.get("post_url"), code):
                already_completed += 1
            else:
                remaining.append(item)
        items = remaining
        if not items:
            await status.edit_text(
                f"✅ All {already_completed} video(s) on this page are already recorded as uploaded.\n\n"
                f"📺 **Channel:** {channel_name}\n📄 **Page:** {page_number}"
            )
            await _delete_status_later(status)
            return

        available = len(items)
        if requested_count < 1 or requested_count > available:
            await status.edit_text(
                f"❌ Invalid video count.\n\n"
                f"📄 **Page:** {page_number}\n"
                f"🎬 **Videos available:** {available}\n"
                f"🔢 **Requested:** {requested_count}\n\n"
                f"Enter a number from 1 to {available}."
            )
            await _delete_status_later(status)
            return

        items = items[:requested_count]
        mode_name = "Parallel" if parallel else "Sequential"
        await status.edit_text(
            f"📥 **{mode_name} mode**\n"
            f"📺 **Channel:** {channel_name}\n"
            f"📄 **Page:** {page_number}\n"
            f"🎬 **Selected:** {len(items)}/{available}"
        )
        if parallel:
            completed, failed = await _run_channel_parallel(message, state, page_number, items, status)
        else:
            completed, failed = await _run_channel_sequential(message, state, page_number, items, status)
        await status.edit_text(
            f"✅ **Page {page_number} complete**\n\n"
            f"📺 **Channel:** {channel_name}\n"
            f"🎬 **Selected:** {len(items)}/{available}\n"
            f"⚡ **Mode:** {mode_name}\n"
            f"✅ **Uploaded:** {completed}\n"
            f"❌ **Failed:** {failed}"
        )
        await _delete_status_later(status)
    except Exception as exc:
        await status.edit_text(
            f"❌ Channel page download failed\n\n{type(exc).__name__}: {exc}"
        )
        await _delete_status_later(status)


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
        target = _configured_channel()
        if not target:
            await status.edit_text(
                "❌ No upload channel is configured yet.\n\n"
                "An administrator can set one with /setchannel @channelname."
            )
            await _delete_status_later(status)
            return
        uploader = "telegram"
    else:
        target = message.chat.id if destination == "telegram" else None
        uploader = destination

    track_upload = uploader == "telegram"
    code = _video_code(state["url"])
    if track_upload:
        try:
            if not processed_store.claim(state["url"], code):
                await status.edit_text("⏭️ This video is already uploaded or currently being processed. Skipping duplicate.")
                await _delete_status_later(status)
                return
        except ProcessedStoreError as exc:
            await status.edit_text(f"❌ Cannot access upload history; refusing to risk a duplicate.\n{exc}")
            await _delete_status_later(status)
            return

    job = Job(
        id=f"TG-{uuid.uuid4().hex[:10]}",
        url=state["url"],
        quality=state["quality"],
        uploader=uploader,
        target=target,
        clips=state.get("clips"),
        caption=state.get("caption"),
        fallback_target=(message.chat.id if destination == "telegram_channel" else None),
    )
    try:
        video, results = await asyncio.to_thread(pipeline.run, job, _progress_callback(progress))
        mode = "clip" if state.get("clips") else "full"
        if track_upload:
            code = code or _video_code(state["url"], video.title)
            processed_store.mark_completed(
                state["url"], code, video.title or "Video",
                destination=destination, message_ids=_message_ids(results),
            )
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
        await _delete_status_later(status)
    except Exception as exc:
        if track_upload:
            processed_store.release(state["url"], code)
        await status.edit_text(f"❌ Pipeline failed or upload history could not be saved\n\n{type(exc).__name__}: {exc}")
        await _delete_status_later(status)


def register_handlers(app: Client):
    @app.on_message(filters.private & filters.command(["setchannel", "unsetchannel", "channel"]))
    async def channel_settings_handler(client, message):
        if not _is_admin(message.from_user.id):
            return await message.reply_text(
                "⛔ Only configured bot admins can change the upload channel. "
                "Set the GitHub Actions secret ADMIN_USER_IDS to your numeric Telegram user ID."
            )

        command = (message.command or ["/channel"])[0].lower().lstrip("/")
        if command == "setchannel":
            if len(message.command or []) < 2:
                return await message.reply_text(
                    "Usage: /setchannel @channelusername\n"
                    "You can also use a numeric channel ID such as -1001234567890.\n\n"
                    "Make sure the bot is an administrator of that channel with permission to post."
                )
            target = message.command[1].strip()
            if not (target.startswith("@") and len(target) > 1 or re.fullmatch(r"-?\d+", target)):
                return await message.reply_text("Invalid channel. Use @channelusername or a numeric channel ID.")
            try:
                await asyncio.to_thread(bot_settings.set_channel, target)
            except Exception as exc:
                return await message.reply_text(f"❌ Could not save channel setting: {type(exc).__name__}: {exc}")
            return await message.reply_text(
                f"✅ Upload channel saved: {target}\n\n"
                "Video uploads will go to this channel when you choose 📢 Channel. "
                "If channel upload fails, the bot will attempt to send the video to this chat instead."
            )

        if command == "unsetchannel":
            try:
                await asyncio.to_thread(bot_settings.clear_channel)
            except Exception as exc:
                return await message.reply_text(f"❌ Could not clear channel setting: {type(exc).__name__}: {exc}")
            return await message.reply_text("✅ Upload channel cleared. Telegram chat uploads remain available.")

        try:
            target = await asyncio.to_thread(_configured_channel)
        except Exception as exc:
            return await message.reply_text(f"❌ Could not read channel setting: {type(exc).__name__}: {exc}")
        return await message.reply_text(
            f"📢 **Upload channel:** {target or 'Not configured'}\n\n"
            "Commands:\n/setchannel @channelusername\n/unsetchannel"
        )

    @app.on_message(filters.private & filters.text)
    async def link_handler(client, message):
        text = message.text.strip()
        if text.split(maxsplit=1)[0].lower() in {"/setchannel", "/unsetchannel", "/channel"}:
            return
        state = pending.get(message.from_user.id)

        if state and state.get("channel_waiting_page"):
            if not re.fullmatch(r"\d+", text):
                return await _reply_and_delete_later(message, "Invalid page number. Use 0 for the first page.")
            page_number = int(text)
            total_pages = int(state.get("total_pages") or 0)
            if page_number < 0 or page_number >= total_pages:
                return await _reply_and_delete_later(message,
                    f"Invalid page. Enter a number from 0 to {max(0, total_pages - 1)}."
                )
            state["channel_page"] = page_number
            state.pop("channel_waiting_page", None)
            state["channel_waiting_count"] = True
            return await _reply_and_delete_later(
                message,
                f"📄 Page **{page_number}** selected.\n\n"
                "How many videos do you want to download from this page?\n"
                "Send a number; the bot will validate it against the page.",
            )

        if state and state.get("channel_waiting_count"):
            if not re.fullmatch(r"\d+", text):
                return await _reply_and_delete_later(message, "Invalid video count. Enter a whole number.")
            count = int(text)
            if count < 1:
                return await _reply_and_delete_later(message, "Video count must be at least 1.")
            state["channel_requested_count"] = count
            state.pop("channel_waiting_count", None)
            state["channel_waiting_mode"] = True
            return await _reply_and_delete_later(
                message,
                f"🎬 **Requested videos:** {count}\n\nChoose download mode:",
                reply_markup=_channel_mode_keyboard(),
            )

        if state and state.get("clip_waiting"):
            match = re.fullmatch(r"\s*([^\-]+)\s*-\s*([^\-]+)\s*", text)
            if not match:
                return await _reply_and_delete_later(message, "Invalid range. Use 00:00-01:30.")
            start, end = match.group(1).strip(), match.group(2).strip()
            if not (_valid_time(start) and _valid_time(end)):
                return await _reply_and_delete_later(message, "Invalid time. Use SS, MM:SS, or HH:MM:SS.")
            if _seconds(end) <= _seconds(start):
                return await _reply_and_delete_later(message, "End time must be after start time.")
            state["clips"] = [(start, end)]
            state.pop("clip_waiting", None)
            await _reply_and_delete_later(message, "✂️ Clip selected. Starting pipeline…")
            try:
                await _run_job(message, state)
            finally:
                pending.pop(message.from_user.id, None)
            return

        if text.startswith("/start"):
            return await _reply_and_delete_later(message, "JAVDL test bot is ready.\n\nSend a supported Javtiful URL to begin.")
        if not text.startswith(("https://javtiful.com/","http://javtiful.com/")):
            return await _reply_and_delete_later(message, "Send a supported Javtiful URL.")

        if re.fullmatch(r"https?://javtiful\.com/channel/[^/?#]+/?(?:\?.*)?", text, re.I):
            status = await message.reply_text("🔎 Inspecting channel…")
            try:
                info = await asyncio.to_thread(channel_extractor.inspect, text)
                total_pages = int(info.get("total_pages") or 1)
                total_videos = info.get("total_videos")
                total_videos_text = str(total_videos) if total_videos is not None else "Not detected"
                first_page_items = info.get("first_page_items") or []
                pending[message.from_user.id] = {
                    "type": "channel",
                    "url": text,
                    "channel_name": info.get("channel_name") or "Channel",
                    "total_videos": total_videos,
                    "total_pages": total_pages,
                }
                await status.edit_text(
                    f"📺 **Channel:** {info.get('channel_name') or 'Channel'}\n"
                    f"🎬 **Total videos in channel:** {total_videos_text}\n"
                    f"📄 **Available pages:** {total_pages}\n"
                    f"📌 **Videos found on page 1:** {len(first_page_items)}\n\n"
                    "Choose an option:",
                    reply_markup=_channel_keyboard(),
                )
                await _delete_status_later(status)
            except Exception as exc:
                await status.edit_text(
                    f"❌ Channel extraction failed\n\n{type(exc).__name__}: {exc}"
                )
                await _delete_status_later(status)
            return
        code = _video_code(text)
        try:
            if processed_store.is_completed(text, code):
                return await _reply_and_delete_later(
                    message,
                    "⏭️ This video is already recorded as uploaded. Skipping duplicate.",
                )
        except ProcessedStoreError as exc:
            return await _reply_and_delete_later(
                message,
                f"❌ Cannot check upload history, so I won't risk a duplicate.\n{exc}",
            )

        status = await message.reply_text("🔎 Extracting video information…")
        try:
            video = extractor.extract(text)
            if not video.qualities:
                await status.edit_text("❌ No downloadable source/quality was exposed by the page.")
                await _delete_status_later(status)
                return
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
            await _delete_status_later(status)
        except Exception as exc:
            await status.edit_text(f"❌ Extraction failed\n\n{type(exc).__name__}: {exc}")
            await _delete_status_later(status)


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
        requested_count = int(state.get("channel_requested_count") or 0)
        state.pop("channel_waiting_mode", None)
        state.pop("channel_page", None)
        state.pop("channel_requested_count", None)
        await query.answer("Starting " + mode + " mode")
        try:
            await _run_channel_page(
                query.message,
                state,
                page_number,
                requested_count,
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

