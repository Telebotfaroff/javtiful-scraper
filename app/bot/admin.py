"""Admin-only diagnostics for the Telegram bot.

This module deliberately reports counts and sanitized titles only; it never
prints source URLs, tokens, API hashes, or raw GitHub API responses.
"""
from datetime import datetime, timezone

from pyrogram import filters


def _format_age(started_at):
    seconds = max(0, int((datetime.now(timezone.utc) - started_at).total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def register_admin_handlers(app, processed_store, bot_settings, is_admin):
    started_at = datetime.now(timezone.utc)

    @app.on_message(filters.private & filters.command(["help", "commands"]))
    async def help_handler(client, message):
        await message.reply_text(
            "🤖 JAVDL Bot Commands\n\n"
            "Send a supported URL to begin.\n"
            "/channel — show upload destination\n"
            "/setchannel — configure destination (admin)\n"
            "/unsetchannel — clear destination (admin)\n"
            "/status — runtime and storage health (admin)\n"
            "/stats — upload-history statistics (admin)\n"
            "/recent — recent completed uploads (admin)\n"
            "/help — show this message"
        )

    @app.on_message(filters.private & filters.command(["status", "stats", "recent"]))
    async def diagnostics_handler(client, message):
        if not message.from_user or not is_admin(message.from_user.id):
            return await message.reply_text("⛔ This command is restricted to configured bot admins.")

        command = (message.command or ["status"])[0].lower().lstrip("/")
        if command == "status":
            try:
                stats = await __import__("asyncio").to_thread(processed_store.summary)
                channel = await __import__("asyncio").to_thread(bot_settings.get_channel)
                text = (
                    "🩺 JAVDL STATUS\n\n"
                    "Bot process: 🟢 Running\n"
                    f"Uptime: {_format_age(started_at)}\n"
                    "Upload history: 🟢 Readable\n"
                    f"History records: {stats['total']}\n"
                    f"Configured channel: {'Yes' if channel else 'No'}"
                )
            except Exception as exc:
                text = (
                    "🩺 JAVDL STATUS\n\n"
                    "Bot process: 🟢 Running\n"
                    "Upload history/settings: 🔴 Unavailable\n"
                    f"Error type: {type(exc).__name__}\n"
                    "Check the GitHub Actions logs for details."
                )
            return await message.reply_text(text)

        try:
            stats = await __import__("asyncio").to_thread(processed_store.summary)
        except Exception as exc:
            return await message.reply_text(
                f"❌ Could not read upload history ({type(exc).__name__}). "
                "Check GitHub Actions logs."
            )

        if command == "stats":
            return await message.reply_text(
                "📊 UPLOAD HISTORY\n\n"
                f"Total records: {stats['total']}\n"
                f"Completed uploads: {stats['completed']}\n"
                f"Other records: {stats['other']}"
            )

        try:
            recent = await __import__("asyncio").to_thread(processed_store.recent_completed, 10)
        except Exception as exc:
            return await message.reply_text(
                f"❌ Could not read recent uploads ({type(exc).__name__})."
            )
        if not recent:
            return await message.reply_text("No completed uploads are recorded yet.")

        lines = ["🕘 RECENT COMPLETED UPLOADS", ""]
        for index, item in enumerate(recent, 1):
            title = str(item.get("title") or "Untitled").replace("\n", " ")[:100]
            code = f" [{item['code']}]" if item.get("code") else ""
            timestamp = item.get("uploaded_at") or "time unknown"
            destination = str(item.get("destination") or "unknown")[:30]
            lines.append(f"{index}. {title}{code}\n   {timestamp} · {destination}")
        return await message.reply_text("\n".join(lines))
