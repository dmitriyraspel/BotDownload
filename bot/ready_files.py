"""Stage a processed media file for later Telegram upload.

Only bot-owned private workspaces are accepted. The caller is responsible for
recording the returned path in SQLite and cleaning it after final delivery.
"""
import os
from pathlib import Path
import stat

from .download_storage import DownloadStorageError, create_task_directory


def stage_ready_file(root: Path, workspace: Path, filename: str, task_id: str) -> Path:
    """Move a regular output file into a new private per-task staging directory.

    Never follows source symlinks; refuses paths and hidden/dot names.
    Both directories must be on the same filesystem for atomic rename.
    """
    if not filename or filename in (".", "..") or Path(filename).name != filename or "\x00" in filename:
        raise DownloadStorageError("Недопустимое имя готового файла")
    root = root.resolve(strict=True)
    if workspace.is_symlink() or workspace.parent != root or not workspace.name.startswith("task-"):
        raise DownloadStorageError("Недопустимый рабочий каталог")
    workspace_stat = workspace.lstat()
    if not stat.S_ISDIR(workspace_stat.st_mode) or workspace_stat.st_uid != os.getuid():
        raise DownloadStorageError("Рабочий каталог не принадлежит процессу")
    source = workspace / filename
    source_stat = source.lstat()
    if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_uid != os.getuid() or source_stat.st_nlink != 1:
        raise DownloadStorageError("Готовый файл должен быть обычным приватным файлом")
    destination_dir = create_task_directory(root, task_id)
    destination = destination_dir / filename
    try:
        source.rename(destination)
    except BaseException:
        destination_dir.rmdir()
        raise
    return destination
