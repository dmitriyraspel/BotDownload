"""Preflight inspection of URLs emitted by yt-dlp.

This is defense in depth, NOT a safe network transport. It cannot protect
requests already made by extractors, redirects or DNS rebinding.
"""
from urllib.parse import urlsplit

from .network_security import UnsafeNetworkTarget, validate_public_https_target


def audit_extracted_media_urls(info: dict, *, max_formats: int = 500) -> int:
    """Reject unsafe protocol URLs before passing formats to a downloader."""
    if not isinstance(info, dict):
        raise UnsafeNetworkTarget("Некорректные метаданные")
    formats = info.get("formats") or []
    if not isinstance(formats, list) or len(formats) > max_formats:
        raise UnsafeNetworkTarget("Слишком много форматов")
    checked = 0
    for entry in [info, *formats]:
        if not isinstance(entry, dict):
            raise UnsafeNetworkTarget("Некорректный формат")
        protocol = entry.get("protocol")
        if protocol and protocol not in ("https",):
            raise UnsafeNetworkTarget("Небезопасный протокол медиа")
        url = entry.get("url")
        if url is None:
            continue
        if not isinstance(url, str) or urlsplit(url).scheme != "https":
            raise UnsafeNetworkTarget("Медиа должно использовать HTTPS")
        validate_public_https_target(url)
        checked += 1
    return checked
