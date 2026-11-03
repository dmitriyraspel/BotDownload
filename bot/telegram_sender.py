"""Telegram Bot API adapter for explicitly approved staged files.

Only accepts local paths already validated by the delivery lifecycle.
Never asks Telegram to fetch a third-party URL.
"""
from pathlib import Path

from aiogram.types import FSInputFile


async def send_staged_file(bot, chat_id: int, path: Path) -> str:
    """Send MP3 as audio, MP4 as video; return confirmed Telegram file_id."""
    path = Path(path)
    if path.suffix.lower() == ".mp3":
        message = await bot.send_audio(
            chat_id=chat_id, audio=FSInputFile(path),
        )
        media = message.audio
    elif path.suffix.lower() == ".mp4":
        message = await bot.send_video(
            chat_id=chat_id, video=FSInputFile(path),
            supports_streaming=True,
        )
        media = message.video
    else:
        raise ValueError("Поддерживаются только MP3 и MP4")
    if media is None or not media.file_id:
        raise RuntimeError("Telegram не подтвердил файл")
    return media.file_id
