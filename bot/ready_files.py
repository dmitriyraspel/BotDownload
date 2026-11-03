"""Stage a processed media file for later Telegram upload.

Only bot-owned private workspaces are accepted. The caller is responsible for
recording the returned path in SQLite and cleaning it after final delivery.
"""
import os
import re
from pathlib import Path
import stat

from .download_storage import DownloadStorageError, create_task_directory

_WORKSPACE = re.compile(r'task-([1-9][0-9]*)-[0-9a-f]{32}\Z')


def stage_ready_file(root: Path, workspace: Path, filename: str, task_id: str) -> Path:
    """Move a regular output file into a new private per-task staging directory.

    Never follows source symlinks; refuses paths and hidden/dot names.
    Both directories must be on the same filesystem for atomic rename.
    """
    if (not isinstance(filename, str) or not filename or filename.startswith(".")
            or filename in (".", "..") or Path(filename).name != filename
            or "\x00" in filename):
        raise DownloadStorageError("Недопустимое имя готового файла")
    root = root.resolve(strict=True)
    match = _WORKSPACE.fullmatch(workspace.name)
    if (workspace.is_symlink() or workspace.parent != root or match is None
            or match.group(1) != task_id):
        raise DownloadStorageError("Недопустимый рабочий каталог")
    workspace_stat = workspace.lstat()
    if (not stat.S_ISDIR(workspace_stat.st_mode) or workspace_stat.st_uid != os.getuid()
            or workspace_stat.st_mode & 0o077):
        raise DownloadStorageError("Рабочий каталог не принадлежит процессу")
    source = workspace / filename
    source_stat = source.lstat()
    if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_uid != os.getuid() or source_stat.st_nlink != 1 or source_stat.st_size <= 0:
        raise DownloadStorageError("Готовый файл должен быть обычным приватным файлом")
    destination_dir = create_task_directory(root, task_id)
    destination = destination_dir / filename
    try:
        source.rename(destination)
    except BaseException:
        destination_dir.rmdir()
        raise
    return destination
