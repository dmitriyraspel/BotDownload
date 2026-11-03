"""Private per-task directories inside the configured download root.

No cleanup operation ever traverses or removes the download root itself.
"""
import os
from pathlib import Path
import re
import shutil
import stat
import uuid


class DownloadStorageError(Exception):
    pass


_TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")


def download_root(configured_path: str, project_root: Path = Path(".")) -> Path:
    """Resolve an existing directory; do not silently create a missing mount."""
    if not configured_path or not configured_path.strip():
        raise DownloadStorageError("Не задан каталог загрузок")
    raw = Path(configured_path).expanduser()
    candidate = raw if raw.is_absolute() else project_root / raw
    if not candidate.is_dir() or candidate.is_symlink():
        raise DownloadStorageError("Каталог загрузок отсутствует или является ссылкой")
    root = candidate.resolve(strict=True)
    if not os.access(root, os.W_OK | os.X_OK):
        raise DownloadStorageError("Нет доступа к каталогу загрузок")
    return root


def create_task_directory(root: Path, task_id: str) -> Path:
    """Create an unpredictable, private directory for one task."""
    if not _TASK_ID.fullmatch(task_id) or task_id in (".", ".."):
        raise DownloadStorageError("Недопустимый ID задачи")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise DownloadStorageError("Каталог загрузок отсутствует")
    for _ in range(5):
        path = root / ("task-" + task_id + "-" + uuid.uuid4().hex)
        try:
            path.mkdir(mode=0o700)
            return path
        except FileExistsError:
            continue
    raise DownloadStorageError("Не удалось создать каталог задачи")


def cleanup_task_directory(root: Path, task_dir: Path) -> None:
    """Remove only an owned task directory, never arbitrary neighboring files.

    Refuse a symlink as the task directory. This is not safe against an
    attacker concurrently modifying the directory; the directory must be
    private to the bot process.
    """
    root = root.resolve(strict=True)
    if task_dir.parent != root or not task_dir.name.startswith("task-"):
        raise DownloadStorageError("Каталог задачи находится вне хранилища")
    if task_dir.is_symlink():
        raise DownloadStorageError("Символическая ссылка вместо каталога задачи")
    try:
        st = task_dir.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise DownloadStorageError("Каталог задачи не принадлежит процессу")
    shutil.rmtree(task_dir)


def require_free_space(root: Path, expected_bytes: int, *, reserve_bytes: int = 512 * 1024 * 1024) -> int:
    """Check free space on the actual download filesystem before starting work.

    This is a preflight check, not a disk quota: concurrent writers may still
    exhaust the disk. The download worker must also enforce output size.
    """
    if type(expected_bytes) is not int or expected_bytes <= 0:
        raise DownloadStorageError("Некорректный ожидаемый размер загрузки")
    if type(reserve_bytes) is not int or reserve_bytes < 0:
        raise DownloadStorageError("Некорректный резерв свободного места")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise DownloadStorageError("Каталог загрузок отсутствует")
    free = shutil.disk_usage(root).free
    if free < expected_bytes + reserve_bytes:
        raise DownloadStorageError("Недостаточно свободного места для загрузки")
    return free
