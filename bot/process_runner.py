"""Bounded subprocess execution for future media workers.

Does not launch downloads by itself. Caller supplies a trusted argv sequence.
"""
import asyncio
import os
import math
import signal
from collections.abc import Sequence
from pathlib import Path


class ProcessExecutionError(Exception):
    pass


def _kill_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        try:
            process.kill()
        except ProcessLookupError:
            pass


async def run_bounded_process(
    argv: Sequence[str], *, cwd: Path, timeout_seconds: float
) -> int:
    """Run trusted argv without a shell, killing descendants on timeout/cancel.

    Caller must enforce resource/network isolation and output limits separately.
    """
    if not argv or any(type(x) is not str or not x or "\x00" in x for x in argv):
        raise ProcessExecutionError("Недопустимая команда")
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ProcessExecutionError("Недопустимый тайм-аут")
    if not isinstance(cwd, Path) or not cwd.is_dir():
        raise ProcessExecutionError("Рабочий каталог отсутствует")
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=(os.name == "posix"),
        )
    except OSError as exc:
        raise ProcessExecutionError("Не удалось запустить внешний процесс") from exc
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        _kill_group(process)
        await process.wait()
        raise ProcessExecutionError("Превышено время выполнения процесса") from exc
    except asyncio.CancelledError:
        _kill_group(process)
        # A second cancellation can interrupt cleanup; use a separate task.
        waiter = asyncio.create_task(process.wait())
        try:
            await asyncio.shield(waiter)
        finally:
            if not waiter.done():
                waiter.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        raise
    if process.returncode != 0:
        raise ProcessExecutionError("Внешний процесс завершился с ошибкой")
    return process.returncode
