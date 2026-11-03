"""Bounded JSON subprocess transport for future metadata isolation.

Not yet wired to Telegram. Unlike asyncio.to_thread, this transport can
terminate the subprocess group when the deadline expires or on cancellation.
Network confinement must be added before handling untrusted URLs with it.
"""
import asyncio
import json
import os
from pathlib import Path
import signal
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
    if (not argv or any(type(x) is not str or not x or "\x00" in x for x in argv)
            or not cwd.is_dir() or not 0 < timeout_seconds < float("inf")
            or type(max_output_bytes) is not int or not 0 < max_output_bytes <= 1048576):
        raise MetadataProcessError("Недопустимые параметры процесса")
    process = await asyncio.create_subprocess_exec(
        *argv, cwd=str(cwd), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=(os.name == "posix"),
    )
    try:
        async def read_result():
            # Read one extra byte to detect oversized output, then stop the group.
            output = await process.stdout.read(max_output_bytes + 1)
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
        await asyncio.shield(process.wait())
        raise
