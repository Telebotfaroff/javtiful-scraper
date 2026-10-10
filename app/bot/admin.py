"""Admin dashboard and diagnostics for the Colab-hosted Telegram bot.

Only configured admin IDs can open diagnostics. Replies intentionally avoid
source URLs, tokens, API hashes, database URLs, and raw credentials.
"""
import asyncio
from datetime import datetime, timezone

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _format_age(started_at):
    seconds = max(0, int((datetime.now(timezone.utc) - started_at).total_seconds()))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🩺 Status", callback_data="admin|status"),
         InlineKeyboardButton("📊 Statistics", callback_data="admin|stats")],
        [InlineKeyboardButton("🕘 Recent uploads", callback_data="admin|recent"),
         InlineKeyboardButton("📢 Channel", callback_data="admin|channel")],
        [InlineKeyboardButton("🔄 Refresh menu", callback_data="admin|menu")],
    ])


def register_admin_handlers(app, processed_store, bot_settings, is_admin):
    started_at = datetime.now(timezone.utc)

    def allowed(user):
        return bool(user and is_admin(user.id))

    async def render(command):
        if command == "menu":
            return (
                "🛠 JAVDL ADMIN PANEL\n\n"
                "Choose a section below. This panel is available only to configured admins.\n\n"
                f"Runtime uptime: {_format_age(started_at)}",
                _admin_keyboard(),
            )
        if command == "status":
            try:
                stats, channel = await asyncio.gather(
                    asyncio.to_thread(processed_store.summary),
                    asyncio.to_thread(bot_settings.get_channel),
                )
                return (
                    "🩺 JAVDL STATUS\n\n"
                    "Bot process: 🟢 Running\n"
                    f"Colab runtime uptime: {_format_age(started_at)}\n"
                    "Upload history: 🟢 Readable\n"
                    f"History records: {stats['total']}\n"
                    f"Completed: {stats['completed']}\n"
                    f"Other records: {stats['other']}\n"
                    f"Upload channel: {'Configured' if channel else 'Not configured'}\n"
                    "Runtime: Google Colab",
                    _admin_keyboard(),
                )
            except Exception as exc:
                return (
                    "🩺 JAVDL STATUS\n\n"
                    "Bot process: 🟢 Running\n"
                    "Storage/settings: 🔴 Check failed\n"
                    f"Error type: {type(exc).__name__}\n"
                    "Check the current Colab output for details.",
                    _admin_keyboard(),
                )
        if command == "stats":
            try:
                stats = await asyncio.to_thread(processed_store.summary)
                return (
                    "📊 UPLOAD HISTORY\n\n"
                    f"Total records: {stats['total']}\n"
                    f"Completed uploads: {stats['completed']}\n"
                    f"Other records: {stats['other']}",
                    _admin_keyboard(),
                )
            except Exception as exc:
                return (f"❌ Could not read upload history ({type(exc).__name__}). Check Colab output.", _admin_keyboard())
        if command == "recent":
            try:
                recent = await asyncio.to_thread(processed_store.recent_completed, 10)
            except Exception as exc:
                return (f"❌ Could not read recent uploads ({type(exc).__name__}).", _admin_keyboard())
            if not recent:
                return ("🕘 No completed uploads are recorded yet.", _admin_keyboard())
            lines = ["🕘 RECENT COMPLETED UPLOADS", ""]
            for index, item in enumerate(recent, 1):
                title = str(item.get("title") or "Untitled").replace("\n", " ")[:90]
                code = f" [{item['code']}]" if item.get("code") else ""
                timestamp = str(item.get("uploaded_at") or "time unknown")[:32]
                destination = str(item.get("destination") or "unknown")[:24]
                lines.append(f"{index}. {title}{code}\n   {timestamp} · {destination}")
            return ("\n".join(lines), _admin_keyboard())
        if command == "channel":
            try:
                channel = await asyncio.to_thread(bot_settings.get_channel)
                value = str(channel) if channel else "Not configured"
                return (
                    "📢 UPLOAD CHANNEL\n\n"
                    f"Current destination: {value}\n\n"
                    "Change it with /setchannel @channelusername or /setchannel -1001234567890.\n"
                    "Clear it with /unsetchannel.",
                    _admin_keyboard(),
                )
            except Exception as exc:
                return (f"❌ Could not read channel settings ({type(exc).__name__}).", _admin_keyboard())
        return ("Unknown admin panel section.", _admin_keyboard())

    @app.on_message(filters.private & filters.command(["help", "commands"]))
    async def help_handler(client, message):
        await message.reply_text(
            "🤖 JAVDL COMMANDS\n\n"
            "General\n"
            "/start — start the bot\n"
            "/help or /commands — show commands\n\n"
            "Admin panel\n"
            "/admin — open interactive admin panel\n"
            "/status — runtime and storage health\n"
            "/stats — upload-history statistics\n"
            "/recent — recent completed uploads\n"
            "/channel — show upload destination\n"
            "/setchannel <channel> — set destination\n"
            "/unsetchannel — clear destination\n\n"
            "Admin commands require your Telegram user ID in ADMIN_USER_IDS."
        )

    @app.on_message(filters.private & filters.command(["admin", "status", "stats", "recent"]))
    async def admin_command_handler(client, message):
        if not allowed(message.from_user):
            return await message.reply_text("⛔ Admin access only.")
        command = (message.command or ["admin"])[0].lower().lstrip("/")
        text, keyboard = await render("menu" if command == "admin" else command)
        await message.reply_text(text, reply_markup=keyboard)

    @app.on_callback_query(filters.regex(r"^admin\|(menu|status|stats|recent|channel)$"))
    async def admin_callback_handler(client, query):
        if not allowed(query.from_user):
            return await query.answer("Admin access only.", show_alert=True)
        command = query.data.split("|", 1)[1]
        await query.answer()
        text, keyboard = await render(command)
        try:
            await query.message.edit_text(text, reply_markup=keyboard)
        except Exception as exc:
            # Telegram raises when the same content is edited again.
            if "MESSAGE_NOT_MODIFIED" not in str(exc).upper():
                raise
