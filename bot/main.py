"""Stage 2 entrypoint: initialize storage and start Telegram polling."""
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import shutil
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from .config import ConfigurationError, load_settings
from .database import initialize
from .telegram_handlers import router


async def run_bot(settings) -> None:
    telegram = settings.data["telegram"]
    session = None
    if telegram["api_mode"] == "local":
        session = AiohttpSession(api=TelegramAPIServer.from_base(telegram["api_base_urls"]["local"]))
    bot = Bot(token=settings.token, session=session)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


def main() -> None:
    try:
        settings = load_settings()
        for executable in ("ffmpeg", "ffprobe"):
            if shutil.which(executable) is None:
                raise ConfigurationError(f"{executable}: исполняемый файл не найден")
        cfg = settings.data["logging"]
        Path("logs").mkdir(exist_ok=True)
        logging.basicConfig(
            level=getattr(logging, cfg["level"]),
            handlers=[
                RotatingFileHandler("logs/bot.log", maxBytes=cfg["max_file_size_mb"] * 1024 * 1024, backupCount=cfg["backup_count"], encoding="utf-8"),
                logging.StreamHandler(),
            ],
            format="%(asctime)s %(levelname)s %(message)s",
        )
        initialize(Path("data/bot.sqlite"))
        logging.info("Запускается Telegram polling (режим %s)", settings.data["telegram"]["api_mode"])
        asyncio.run(run_bot(settings))
    except (ConfigurationError, OSError, RuntimeError) as exc:
        print(f"Ошибка запуска: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        logging.info("Остановка бота")
