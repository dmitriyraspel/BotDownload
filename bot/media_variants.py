"""Build truthful media variants from yt-dlp metadata."""
from math import isfinite

TARGET_HEIGHTS = (480, 720, 1080)


def estimated_bytes(fmt: dict, duration: object = None) -> tuple[int | None, bool]:
    exact = fmt.get("filesize")
    if isinstance(exact, (int, float)) and isfinite(exact) and exact > 0:
        return int(exact), False
    approx = fmt.get("filesize_approx")
    if isinstance(approx, (int, float)) and isfinite(approx) and approx > 0:
        return int(approx), True
    bitrate = fmt.get("tbr") or (fmt.get("abr") if fmt.get("vcodec") in (None, "none") else None)
    if (isinstance(bitrate, (int, float)) and not isinstance(bitrate, bool)
            and isfinite(bitrate) and bitrate > 0
            and isinstance(duration, (int, float)) and not isinstance(duration, bool)
            and isfinite(duration) and duration > 0):
        return int(bitrate * 1000 * duration / 8), True
    return None, True


def mp3_estimate(info: dict) -> int | None:
    duration = info.get("duration")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not isfinite(duration) or duration <= 0:
        return None
    audio = _preferred_audio([f for f in info.get("formats", []) if isinstance(f, dict)])
    if audio is None:
        return None
    bitrate = audio.get("abr") or audio.get("tbr")
    if not isinstance(bitrate, (int, float)) or isinstance(bitrate, bool) or not isfinite(bitrate) or bitrate <= 0:
        return None
    # Approximation from source bitrate, not the final VBR encoder output.
    return int(min(bitrate, 320) * 1000 * duration / 8)


def _preferred_audio(formats: list[dict]) -> dict | None:
    audio = [f for f in formats if f.get("acodec") not in (None, "none")
             and f.get("vcodec") in (None, "none")]
    russian = [f for f in audio if str(f.get("language") or "").lower().split("-")[0] == "ru"]
    pool = russian or audio
    return max(pool, key=lambda f: f.get("abr") or f.get("tbr") or 0) if pool else None


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
    duration = info.get("duration")
    audio_stream = _preferred_audio(formats)
    for height in TARGET_HEIGHTS:
        candidates = [f for f in formats if f.get("vcodec") not in (None, "none")
                      and f.get("height") == height]
        if not candidates:
            continue
        # A separate audio stream may be required; don't claim an exact final size.
        candidate = max(candidates, key=lambda f: (f.get("tbr") or 0))
        size, approximate = estimated_bytes(candidate, duration)
        if candidate.get("acodec") in (None, "none"):
            if audio_stream is not None:
                audio_size, _ = estimated_bytes(audio_stream, duration)
                size = size + audio_size if size is not None and audio_size is not None else None
            else:
                size = None
            approximate = True
        result.append({"kind": "video", "quality": f"{height}p", "size": size,
                       "approximate": approximate or candidate.get("acodec") in (None, "none")})
    if any(f.get("acodec") not in (None, "none") for f in formats):
        result.append({"kind": "mp3", "quality": "MP3", "size": mp3_estimate(info), "approximate": True})
    return result


def size_label(size: int | None, approximate: bool) -> str:
    if size is None:
        return "размер неизвестен"
    return f"{'≈ ' if approximate else ''}{size / (1024 * 1024):.1f} МиБ"
