import asyncio
import logging
import os
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from aiogram import Bot
from aiogram.enums import ParseMode

from bot import BotService
from checker import DomainChecker, NotificationService
from database import Database


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


async def main() -> None:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Переменная окружения TELEGRAM_BOT_TOKEN не установлена")

    db = Database()
    await db.init()

    bot_instance = Bot(token, parse_mode=ParseMode.HTML)
    notifier = NotificationService(bot_instance, db)
    checker = DomainChecker(db, notifier)
    bot_service = BotService(bot_instance, db, checker)

    await checker.check_all_domains()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        checker.check_all_domains,
        "interval",
        minutes=5,
        jitter=300,
        next_run_time=datetime.utcnow() + timedelta(seconds=5),
    )
    scheduler.start()

    try:
        await bot_service.run()
    finally:
        scheduler.shutdown(wait=False)
        await bot_service.stop()


if __name__ == "__main__":
    asyncio.run(main())
