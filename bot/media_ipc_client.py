"""Broker-side authenticated execution and atomic staging of a media result."""
import asyncio
import json
import os
from pathlib import Path
import stat

from .download_storage import download_root, cleanup_task_directory
from .ready_files import stage_ready_file
from .storage import database, change_status, mark_file_ready, task_is_cancelled
from .worker_ipc import WorkerProtocolError


async def request_media_execution(socket_path: Path, task_id: int, token: str) -> Path:
    from .worker_reservations import valid_token
    if not socket_path.is_absolute() or not valid_token(token):
        raise WorkerProtocolError("Неверные параметры выполнения")
    async with asyncio.timeout(145):
        reader, writer = await asyncio.open_unix_connection(str(socket_path))
        try:
            writer.write(json.dumps(
                {"version": 1, "op": "execute_media", "task_id": task_id, "token": token},
                separators=(",", ":"),
            ).encode() + b"\n")
            await writer.drain()
            raw = await reader.readline()
            if not 0 < len(raw) <= 4096 or not raw.endswith(b"\n"):
                raise WorkerProtocolError("Неверный ответ media worker")
            result = json.loads(raw)
            if (not isinstance(result, dict)
                    or set(result) != {"version", "status", "downloads_enabled", "file"}
                    or result["version"] != 1 or result["status"] != "completed"
                    or result["downloads_enabled"] is not True
                    or not isinstance(result["file"], str)):
                raise WorkerProtocolError("Загрузка не завершилась")
            return Path(result["file"])
        finally:
            writer.close()
            await writer.wait_closed()


def publish_media_file(
    *, db_path: Path, task_id: int, result: Path,
    configured_download_dir: str,
) -> bool:
    root = download_root(configured_download_dir)
    # A worker-supplied path is untrusted. Restrict it to a direct child
    # of an owned private task directory; never resolve a symlink.
    if not result.is_absolute() or result.is_symlink():
        raise WorkerProtocolError("Небезопасный путь результата")
    directory = result.parent
    if directory.parent != root or directory.is_symlink():
        raise WorkerProtocolError("Результат вне хранилища")
    from .ready_files import _WORKSPACE
    match = _WORKSPACE.fullmatch(directory.name)
    if match is None or match.group(1) != str(task_id):
        raise WorkerProtocolError("Чужой каталог задачи")
    st = result.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
            or st.st_nlink != 1 or not 0 < st.st_size <= 256 * 1024 * 1024):
        raise WorkerProtocolError("Недопустимый файл")
    with database(db_path) as db:
        if task_is_cancelled(db, task_id):
            return False
        if not change_status(db, task_id, "downloading", "processing"):
            raise WorkerProtocolError("Задача изменила состояние")
    staged = stage_ready_file(root, directory, result.name, str(task_id))
    with database(db_path) as db:
        if not mark_file_ready(db, task_id, str(staged)):
            raise WorkerProtocolError("Не удалось опубликовать файл")
    cleanup_task_directory(root, directory)
    return True
