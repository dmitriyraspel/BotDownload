"""Metadata-only inspection for supported media sites."""
import asyncio

import yt_dlp

from .telegram_handlers import validate_media_url
from .local_tools import yt_dlp_js_options
from .media_variants import available_variants, selected_language


class AnalysisError(Exception):
    pass


def _extract(url: str) -> dict:
    # No generic extractor: only known site extractors may handle the URL.
    opts = {
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "allowed_extractors": ["youtube", "youtube:tab", "Instagram", "TikTok"],
        "socket_timeout": 10,
        "retries": 0,
        "extractor_retries": 0,
        **yt_dlp_js_options(),
    }
    with yt_dlp.YoutubeDL(opts) as downloader:
        info = downloader.extract_info(url, download=False)
    if not isinstance(info, dict):
        raise AnalysisError("Не удалось получить сведения о видео")
    return {
        "title": str(info.get("title") or "Без названия")[:200],
        "duration": info.get("duration"),
        "uploader": str(info.get("uploader") or info.get("channel") or "")[:100],
        "upload_date": str(info.get("upload_date") or ""),
        "view_count": info.get("view_count"),
        "extractor": str(info.get("extractor_key") or ""),
        "thumbnail": str(info.get("thumbnail") or ""),
        "language": selected_language(info),
        "variants": available_variants(info),
    }


async def inspect(url: str, timeout: int = 60) -> dict:
    if not validate_media_url(url):
        raise AnalysisError("Недопустимая ссылка")
    try:
        return await asyncio.wait_for(asyncio.to_thread(_extract, url), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise AnalysisError("Превышено время анализа") from exc
    except yt_dlp.utils.DownloadError as exc:
        raise AnalysisError("Не удалось получить информацию по ссылке") from exc
