"""Bounded JSON subprocess transport for future metadata isolation.

Telegram inspection is fail-closed until an enforced guard is installed. Unlike asyncio.to_thread, this transport can
terminate the subprocess group when the deadline expires or on cancellation.
Network confinement must be added before handling untrusted URLs with it.
"""
import asyncio
import json
import math
import os
from pathlib import Path
import signal
import sys
from collections.abc import Sequence


class MetadataProcessError(RuntimeError):
    pass


def _kill_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass


async def run_json_subprocess(
    argv: Sequence[str], *, cwd: Path, timeout_seconds: float,
    max_output_bytes: int = 262144,
) -> dict:
    if (not isinstance(argv, (list, tuple)) or not argv
            or any(type(x) is not str or not x or "\x00" in x for x in argv)
            or not isinstance(cwd, Path) or not cwd.is_dir()
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0
            or type(max_output_bytes) is not int or not 0 < max_output_bytes <= 1048576):
        raise MetadataProcessError("Недопустимые параметры процесса")
    try:
        process = await asyncio.create_subprocess_exec(
            *argv, cwd=str(cwd), stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=(os.name == "posix"),
        )
    except OSError as exc:
        raise MetadataProcessError("Не удалось запустить анализатор") from exc
    try:
        async def read_result():
            # Read one extra byte to detect oversized output, then stop the group.
            try:
                output = await process.stdout.readexactly(max_output_bytes + 1)
            except asyncio.IncompleteReadError as exc:
                output = exc.partial
            if len(output) > max_output_bytes:
                raise MetadataProcessError("Слишком большой ответ анализатора")
            # EOF may not arrive until all descendants close stdout.
            await process.wait()
            if process.returncode != 0:
                raise MetadataProcessError("Анализатор завершился с ошибкой")
            try:
                data = json.loads(output)
            except (UnicodeError, ValueError) as exc:
                raise MetadataProcessError("Некорректный ответ анализатора") from exc
            if not isinstance(data, dict):
                raise MetadataProcessError("Ожидался объект метаданных")
            return data

        return await asyncio.wait_for(read_result(), timeout=timeout_seconds)
    except BaseException:
        _kill_group(process)
        waiter = asyncio.create_task(process.wait())
        try:
            await asyncio.shield(waiter)
        finally:
            if not waiter.done():
                waiter.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        raise


async def inspect_in_subprocess(
    url: str, *, timeout_seconds: float,
    network_guard: object | None = None,
) -> dict:
    """Process-managed inspection; NOT safe for untrusted URLs until egress is confined."""
    from .network_security import validate_public_https_target
    # The preflight below is not a substitute for a kernel-enforced egress
    # boundary. Refuse to spawn a networked extractor until one is supplied.
    if network_guard is None:
        raise MetadataProcessError("Не настроена изоляция сетевых соединений")
    if not callable(network_guard):
        raise MetadataProcessError("Некорректная политика сетевой изоляции")
    from .telegram_handlers import ALLOWED_HOSTS, validate_media_url

    if not validate_media_url(url):
        raise MetadataProcessError("Недопустимая ссылка")
    # Defense in depth only: DNS results are not pinned to yt-dlp sockets.
    await asyncio.to_thread(validate_public_https_target, url, allowed_hosts=ALLOWED_HOSTS)
    project_root = Path(__file__).resolve().parent.parent
    command = network_guard([sys.executable, "-m", "bot.metadata_worker", url])
    original_command = [sys.executable, "-m", "bot.metadata_worker", url]
    if (not isinstance(command, (list, tuple)) or not command
            or any(type(arg) is not str or not arg or "\x00" in arg for arg in command)
            or list(command) == original_command):
        raise MetadataProcessError("Не применена изоляция сетевых соединений")
    return await run_json_subprocess(
        command,
        cwd=project_root, timeout_seconds=timeout_seconds,
    )
