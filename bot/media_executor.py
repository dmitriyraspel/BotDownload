"""Opt-in media executor for isolated tests; never wired to Telegram.

The subprocess is a separate process group with bounded CPU, memory, output
file size and elapsed time. URL admission is intentionally conservative.
Network-level egress filtering is still required before production enablement.
"""
import asyncio
import ipaddress
import os
from pathlib import Path
import re
import resource
import signal
import stat
import sys
from urllib.parse import urlsplit

from .download_storage import create_task_directory, download_root, require_free_space


class UnsafeMediaRequest(ValueError):
    pass


_ALLOWED = frozenset({
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "youtu.be", "www.youtu.be",
})
_HOST = re.compile(r"[a-z0-9.-]+\\Z")
_MAX_URL = 2048


def validate_media_url(url: str) -> str:
    if not isinstance(url, str) or not 1 <= len(url) <= _MAX_URL:
        raise UnsafeMediaRequest("Недопустимая длина URL")
    if any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise UnsafeMediaRequest("Недопустимые символы URL")
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise UnsafeMediaRequest("Некорректный URL") from exc
    if (parsed.scheme != "https" or not hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.fragment or port not in (None, 443)
            or not _HOST.fullmatch(hostname)
            or hostname not in _ALLOWED):
        raise UnsafeMediaRequest("Источник не разрешён")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise UnsafeMediaRequest("IP-адреса запрещены")
    return url


def _limits(max_bytes: int, cpu_seconds: int, memory_bytes: int) -> None:
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (max_bytes, max_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


async def execute_media_download(
    url: str, *, configured_download_dir: str,
    timeout_seconds: int = 120, max_bytes: int = 256 * 1024 * 1024,
    memory_bytes: int = 1024 * 1024 * 1024,
    cancel: asyncio.Event | None = None,
    project_root: Path = Path("."),
    enabled: bool = False,
) -> Path:
    """Return a private task directory; caller owns cleanup.

    Disabled by default. Not suitable for production without network egress
    isolation and redirect/secondary-request policy enforcement.
    """
    if not enabled:
        raise UnsafeMediaRequest("Реальные загрузки отключены")
    validate_media_url(url)
    if (type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 3600
            or type(max_bytes) is not int or not 1 <= max_bytes <= 2**31
            or type(memory_bytes) is not int or not 128 * 1024**2 <= memory_bytes <= 8 * 1024**3):
        raise UnsafeMediaRequest("Недопустимые ограничения ресурсов")
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError()
    root = download_root(configured_download_dir, project_root)
    require_free_space(root, max_bytes)
    workspace = create_task_directory(root, "media")
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "yt_dlp",
            "--no-config", "--no-playlist", "--no-cache-dir",
            "--no-write-info-json", "--no-write-thumbnail",
            "--no-write-subs", "--no-write-auto-subs",
            "--restrict-filenames", "--max-filesize", str(max_bytes),
            "--socket-timeout", "10", "--retries", "0",
            "--fragment-retries", "0",
            "--output", "%(id).80s.%(ext)s",
            "--", url,
            cwd=workspace, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
            preexec_fn=lambda: _limits(max_bytes, timeout_seconds + 2, memory_bytes),
        )
        waiter = asyncio.create_task(proc.wait())
        canceller = asyncio.create_task(cancel.wait()) if cancel else None
        try:
            done, _ = await asyncio.wait(
                [waiter] + ([canceller] if canceller else []),
                timeout=timeout_seconds, return_when=asyncio.FIRST_COMPLETED,
            )
            if not done or (canceller is not None and canceller in done):
                raise asyncio.CancelledError() if canceller is not None and canceller in done else TimeoutError("Время загрузки истекло")
            if waiter.result() != 0:
                raise RuntimeError("Загрузка завершилась с ошибкой")
        finally:
            if canceller is not None:
                canceller.cancel()
            if proc.returncode is None:
                os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
            waiter.cancel()
        files = list(workspace.iterdir())
        if len(files) != 1:
            raise RuntimeError("Неоднозначный результат загрузки")
        item = files[0]
        info = item.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_size <= 0 or info.st_size > max_bytes):
            raise RuntimeError("Небезопасный результат загрузки")
        return workspace
    except BaseException:
        from .download_storage import cleanup_task_directory
        cleanup_task_directory(root, workspace)
        raise
