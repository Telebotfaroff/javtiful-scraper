import logging
import os

from pyrogram import Client
from app.bot.handlers import register_handlers


def create_app():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    app = Client(
        os.getenv("TELEGRAM_SESSION", "javdl"),
        api_id=int(os.environ["TELEGRAM_API_ID"]),
        api_hash=os.environ["TELEGRAM_API_HASH"],
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
    )
    register_handlers(app)
    return app


def run():
    create_app().run()
