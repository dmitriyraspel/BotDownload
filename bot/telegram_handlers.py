"""Telegram stage 2: basic commands and conservative link intake."""
from urllib.parse import urlsplit
import ipaddress
import socket

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

router = Router()

ALLOWED_HOSTS = {
    "youtube.com", "youtu.be", "instagram.com", "tiktok.com",
}


def validate_media_url(value: str) -> bool:
    """Only permit HTTPS links to known media domains; no DNS requests here."""
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() for c in value):
        return False
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").rstrip(".").lower()
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
            return False
        if not host or host not in ALLOWED_HOSTS and not any(host.endswith("." + domain) for domain in ALLOWED_HOSTS):
            return False
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            return True
    except ValueError:
        return False


@router.message(Command("start"))
async def start(message: Message) -> None:
    await message.answer("Привет! Отправь HTTPS-ссылку на YouTube, Instagram или TikTok. Загрузка появится на следующем шаге разработки.")


@router.message(Command("myid"))
async def myid(message: Message) -> None:
    if message.from_user:
        await message.answer(f"Твой Telegram ID: {message.from_user.id}")


@router.message(F.text)
async def link(message: Message) -> None:
    value = (message.text or "").strip()
    if validate_media_url(value):
        await message.answer("Ссылка принята. Анализ и скачивание будут добавлены на следующем шаге.")
    else:
        await message.answer("Отправь одну HTTPS-ссылку на YouTube, Instagram или TikTok.")
