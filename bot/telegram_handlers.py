"""Telegram commands and conservative link intake."""
from urllib.parse import urlsplit

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

router = Router()
ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "instagram.com", "www.instagram.com", "tiktok.com", "www.tiktok.com", "m.tiktok.com"}


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
    from .media_variants import size_label
    duration = info.get("duration")
    duration_text = (f"{int(duration) // 60}:{int(duration) % 60:02d}"
                     if isinstance(duration, (int, float)) and not isinstance(duration, bool)
                     and duration >= 0 else "неизвестна")
    date = info.get("upload_date", "")
    published = f"{date[6:8]}.{date[4:6]}.{date[:4]}" if len(date) == 8 and date.isdigit() else "неизвестна"
    views = info.get("view_count")
    views_text = f"{views:,}".replace(",", " ") if isinstance(views, int) and views >= 0 else "неизвестно"
    uploader = info.get("uploader") or "неизвестен"
    buttons = []
    video_row = []
    for variant in info.get("variants", []):
        quality = variant["quality"]
        kind = variant["kind"]
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > 0:
            limit = settings.data["limits"]["max_audio_duration_seconds" if kind == "mp3" else "max_video_duration_seconds"]
            if duration > limit:
                continue
        size = size_label(variant["size"], variant["approximate"])
        if kind == "video":
            video_row.append(InlineKeyboardButton(text=f"{quality} ({size})", callback_data=f"preview:{quality}"))
            if len(video_row) == 2:
                buttons.append(video_row)
                video_row = []
        else:
            if video_row:
                buttons.append(video_row)
                video_row = []
            buttons.append([InlineKeyboardButton(text=f"🎵 Скачать только аудио MP3 ({size})", callback_data="preview:MP3")])
    if video_row:
        buttons.append(video_row)
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="preview:cancel")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    card = (f"{info['title']} | {uploader}\\n"
            f"Дата публикации: {published}\\n"
            f"Продолжительность: {duration_text}\\n"
            f"Просмотров: {views_text}\\n\\n"
            f"Выбранный язык: {info.get('language', 'Язык аудио не определён')}\\n\\n"
            "Выберите качество:" if len(buttons) > 1 else
            f"{info['title']}\\nДоступные варианты не определены.")
    # Do not ask Telegram to fetch arbitrary third-party URLs.
    # Only YouTube's dedicated thumbnail CDN is accepted for this preview.
    thumbnail = info.get("thumbnail", "")
    from urllib.parse import urlsplit as _split
    try:
        thumb_url = _split(thumbnail)
        trusted_thumbnail = (thumb_url.scheme == "https" and
                             thumb_url.hostname in ("i.ytimg.com", "img.youtube.com") and
                             not thumb_url.username and not thumb_url.password and
                             thumb_url.port in (None, 443))
    except ValueError:
        trusted_thumbnail = False
    if trusted_thumbnail and len(card) <= 1024:
        try:
            await message.answer_photo(photo=thumbnail, caption=card, reply_markup=keyboard)
            return
        except Exception:
            # Thumbnail failures should not prevent a metadata card.
            pass
    await message.answer(card, reply_markup=keyboard)


@router.callback_query(F.data.in_({"preview:480p", "preview:720p", "preview:1080p", "preview:MP3"}))
async def preview_format(callback: CallbackQuery) -> None:
    await callback.answer("Формат выбран. Скачивание пока не включено.", show_alert=True)


@router.callback_query(F.data == "preview:cancel")
async def cancel_preview(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Выбор отменён")
