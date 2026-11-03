"""Offline-only bounded job executor.

This executor intentionally runs a fixed Python module, never a user-supplied
command, URL or path. It is not wired to the production worker or Telegram.
"""
import asyncio
import os
import math
from pathlib import Path
import signal
import sys


class OfflineExecutionError(RuntimeError):
    pass


async def execute_offline_job(
    workspace: Path, *, timeout_seconds: float = 10,
    max_output_bytes: int = 1024 * 1024,
    cancel: asyncio.Event | None = None,
) -> Path:
    """Create a small deterministic artifact using a fixed subprocess.

    Process group is killed on timeout, cancellation or external task cancel.
    Only a pre-created private directory may be used.
    """
    if (not isinstance(workspace, Path) or not workspace.is_absolute()
            or workspace.is_symlink() or not workspace.is_dir()
            or workspace.stat().st_uid != os.geteuid()
            or workspace.stat().st_mode & 0o077):
        raise OfflineExecutionError("Рабочий каталог должен быть приватным")
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 3600
            or type(max_output_bytes) is not int or not 0 < max_output_bytes <= 1024 * 1024):
        raise OfflineExecutionError("Недопустимые ограничения")
    if cancel is not None and not isinstance(cancel, asyncio.Event):
        raise OfflineExecutionError("Недопустимый сигнал отмены")
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError
    target = workspace / "offline-result.bin"
    if target.exists() or target.is_symlink():
        raise OfflineExecutionError("Выходной файл уже существует")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-I", "-c",
        "import pathlib; pathlib.Path('offline-result.bin').write_bytes(b'offline-worker-ok')",
        cwd=str(workspace), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    waiter = asyncio.create_task(proc.wait())
    cancel_waiter = asyncio.create_task(cancel.wait()) if cancel is not None else None
    try:
        pending = {waiter}
        if cancel_waiter is not None:
            pending.add(cancel_waiter)
        done, _ = await asyncio.wait(pending, timeout=timeout_seconds,
                                     return_when=asyncio.FIRST_COMPLETED)
        if cancel_waiter is not None and cancel_waiter in done:
            raise asyncio.CancelledError
        if waiter not in done:
            raise OfflineExecutionError("Превышен лимит времени")
        if proc.returncode != 0:
            raise OfflineExecutionError("Процесс завершился с ошибкой")
        info = target.lstat()
        import stat
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.geteuid() or info.st_size > max_output_bytes):
            raise OfflineExecutionError("Недопустимый результат")
        target.chmod(0o600)
        return target
    except BaseException:
        if proc.returncode is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await asyncio.shield(proc.wait())
        target.unlink(missing_ok=True)
        raise
    finally:
        if cancel_waiter is not None:
            cancel_waiter.cancel()
            await asyncio.gather(cancel_waiter, return_exceptions=True)
        if not waiter.done():
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
