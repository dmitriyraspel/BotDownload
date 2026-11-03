"""Telegram commands and conservative link intake."""
from urllib.parse import urlsplit

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

router = Router()
ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "instagram.com", "www.instagram.com", "tiktok.com", "www.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}


def validate_media_url(value: str) -> bool:
    """Require HTTPS, a supported host, and a single unambiguous URL."""
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() or ord(c) < 32 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or not host or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.fragment
                or "\\" in value or not parsed.path.startswith("/")
                or any(seq in value.lower() for seq in ("%0a", "%0d", "%00", "%09"))):
            return False
        if host not in ALLOWED_HOSTS:
            return False
        # Disallow non-ASCII domain spellings and unusual URL authorities.
        if not host.isascii() or "%" in parsed.netloc or "@" in parsed.netloc:
            return False
        return True
    except ValueError:
        return False


@router.message(Command("start"))
async def start(message: Message) -> None:
    await message.answer("Привет! Отправь HTTPS-ссылку на YouTube, Instagram или TikTok для анализа.")


@router.message(Command("myid"))
async def myid(message: Message) -> None:
    if message.from_user:
        await message.answer(f"Твой Telegram ID: {message.from_user.id}")


@router.message(F.text)
async def link(message: Message) -> None:
    value = (message.text or "").strip()
    if not validate_media_url(value):
        await message.answer("Отправь одну HTTPS-ссылку на YouTube, Instagram или TikTok.")
        return
    from .metadata import AnalysisError, inspect
    from .config import load_settings
    settings = load_settings()
    await message.answer("Анализирую ссылку…")
    try:
        info = await inspect(value, timeout=settings.data["timeouts"]["analysis_timeout_seconds"])
    except AnalysisError as exc:
        await message.answer(str(exc))
        return
    duration = info.get("duration")
    duration_text = f"{int(duration)} сек." if isinstance(duration, (int, float)) and duration >= 0 else "неизвестна"
    buttons = []
    if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > 0:
        if duration <= settings.data["limits"]["max_video_duration_seconds"]:
            buttons.append(InlineKeyboardButton(text="🎬 Видео", callback_data="preview:video"))
        if duration <= settings.data["limits"]["max_audio_duration_seconds"]:
            buttons.append(InlineKeyboardButton(text="🎵 MP3", callback_data="preview:mp3"))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons]) if buttons else None
    note = ("Выбери формат (скачивание пока отключено)." if buttons
            else "Скачивание недоступно: неизвестная или слишком большая длительность.")
    await message.answer(
        f"Название: {info['title']}\\nДлительность: {duration_text}\\n{note}",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.in_({"preview:video", "preview:mp3"}))
async def preview_format(callback: CallbackQuery) -> None:
    await callback.answer("Формат выбран. Скачивание пока не включено.", show_alert=True)
