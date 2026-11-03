"""Build truthful media variants from yt-dlp metadata."""
from math import isfinite

TARGET_HEIGHTS = (480, 720, 1080)


def estimated_bytes(fmt: dict) -> tuple[int | None, bool]:
    exact = fmt.get("filesize")
    if isinstance(exact, (int, float)) and isfinite(exact) and exact > 0:
        return int(exact), False
    approx = fmt.get("filesize_approx")
    if isinstance(approx, (int, float)) and isfinite(approx) and approx > 0:
        return int(approx), True
    return None, True


def selected_language(info: dict) -> str:
    audio = [f for f in info.get("formats", []) if isinstance(f, dict)
             and f.get("acodec") not in (None, "none")]
    russian = next((f for f in audio if str(f.get("language") or "").lower().split("-")[0] == "ru"), None)
    if russian:
        return "Русский"
    language = info.get("language") or next((f.get("language") for f in audio if f.get("language")), None)
    return str(language) if language else "Язык аудио не определён"


def available_variants(info: dict) -> list[dict]:
    formats = [f for f in info.get("formats", []) if isinstance(f, dict)]
    result = []
    for height in TARGET_HEIGHTS:
        candidates = [f for f in formats if f.get("vcodec") not in (None, "none")
                      and f.get("height") == height]
        if not candidates:
            continue
        # A separate audio stream may be required; don't claim an exact final size.
        candidate = max(candidates, key=lambda f: (f.get("tbr") or 0))
        size, approximate = estimated_bytes(candidate)
        result.append({"kind": "video", "quality": f"{height}p", "size": size,
                       "approximate": approximate or candidate.get("acodec") in (None, "none")})
    if any(f.get("acodec") not in (None, "none") for f in formats):
        result.append({"kind": "mp3", "quality": "MP3", "size": None, "approximate": True})
    return result


def size_label(size: int | None, approximate: bool) -> str:
    if size is None:
        return "размер неизвестен"
    return f"{'≈ ' if approximate else ''}{size / (1024 * 1024):.1f} МиБ"
