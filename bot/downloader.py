"""Bounded media download engine. Not connected to Telegram handlers yet.

Network isolation / SSRF controls are required before enabling this for untrusted links.
"""
import asyncio
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from .local_tools import deno_path
from .process_runner import ProcessExecutionError, run_bounded_process
from .telegram_handlers import validate_media_url
from collections.abc import Callable, Sequence


class DownloadError(Exception):
    """Download rejected or failed."""


def check_duration(duration: object, maximum_seconds: int) -> None:
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        raise DownloadError("Длительность неизвестна: скачивание запрещено")
    if duration > maximum_seconds:
        raise DownloadError("Видео превышает ограничение по длительности")


def check_size(size: object, maximum_bytes: int) -> None:
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise DownloadError("Размер неизвестен: скачивание запрещено")
    if size > maximum_bytes:
        raise DownloadError("Файл превышает допустимый размер")


def build_command(url: str, mode: str, max_bytes: int, output: Path) -> list[str]:
    if not validate_media_url(url):
        raise DownloadError("Недопустимая ссылка")
    if mode not in ("video", "mp3"):
        raise DownloadError("Неизвестный формат")
    if max_bytes <= 0:
        raise DownloadError("Недопустимый лимит размера")
    command = [
        sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
        "--no-progress", "--no-warnings", "--no-overwrites",
        "--max-filesize", str(max_bytes), "--socket-timeout", "10",
        "--retries", "0", "--extractor-retries", "0",
        "--output", str(output / "%(id)s.%(ext)s"),
    ]
    deno = deno_path()
    if deno:
        command.extend(["--js-runtimes", f"deno:{deno}"])
    if mode == "mp3":
        command.extend(["--extract-audio", "--audio-format", "mp3"])
    else:
        command.extend(["--format", "bv*+ba/b"])
    return command + ["--", url]


async def download_to_temporary(url: str, mode: str, duration: object,
                                max_duration_seconds: int, max_bytes: int,
                                timeout_seconds: int, *,
                                network_guard: Callable[[list[str]], Sequence[str]] | None = None,
                                ) -> tuple[TemporaryDirectory, Path]:
    """Return an owned temp directory and resulting file; caller MUST cleanup.

    Preflight checks cannot replace sandboxing, and post-conversion file sizes
    may exceed the source-size limit; both are verified before returning.
    """
    if network_guard is None or not callable(network_guard):
        raise DownloadError("Не настроена изоляция сетевых соединений загрузчика")
    check_duration(duration, max_duration_seconds)
    temporary = TemporaryDirectory(prefix="botdownload-")
    directory = Path(temporary.name)
    try:
        command = build_command(url, mode, max_bytes, directory)
        guarded = network_guard(command)
        if (not isinstance(guarded, (list, tuple)) or not guarded
                or any(type(arg) is not str or not arg or "\x00" in arg for arg in guarded)
                or list(guarded) == command):
            raise DownloadError("Не применена изоляция сетевых соединений загрузчика")
        try:
            await run_bounded_process(
                list(guarded), cwd=directory, timeout_seconds=timeout_seconds,
            )
        except ProcessExecutionError as exc:
            raise DownloadError("Не удалось скачать или обработать файл") from exc
        files = [p for p in directory.iterdir() if p.is_file()]
        if len(files) != 1:
            raise DownloadError("Неоднозначный результат скачивания")
        result = files[0]
        if mode == "mp3" and result.suffix.lower() != ".mp3":
            raise DownloadError("Не удалось преобразовать файл в MP3")
        check_size(result.stat().st_size, max_bytes)
        return temporary, result
    except BaseException:
        temporary.cleanup()
        raise
