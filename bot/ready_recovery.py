"""Validate persisted upload files without following untrusted filesystem paths.

Recovery is read-only with respect to files. A missing/invalid file is marked
failed only if the task is still upload_pending; no directories are removed.
"""
import os
from pathlib import Path
import re
import stat

from .download_storage import download_root
from .storage import database

_READY_DIR = re.compile(r"task-([1-9][0-9]*)-[0-9a-f]{32}\Z")


def valid_ready_file(root: Path, task_id: int, stored_path: str) -> bool:
    """Accept only an owned, regular, single-link file in this task's directory."""
    if type(task_id) is not int or task_id <= 0 or not isinstance(stored_path, str):
        return False
    try:
        path = Path(stored_path)
        if not path.is_absolute() or path.parent.parent != root:
            return False
        match = _READY_DIR.fullmatch(path.parent.name)
        if match is None or int(match.group(1)) != task_id:
            return False
        if path.name in ("", ".", "..") or path.is_symlink() or path.parent.is_symlink():
            return False
        directory = path.parent.lstat()
        file_stat = path.lstat()
        return (
            stat.S_ISDIR(directory.st_mode)
            and directory.st_uid == os.getuid()
            and stat.S_ISREG(file_stat.st_mode)
            and file_stat.st_uid == os.getuid()
            and file_stat.st_nlink == 1
            and file_stat.st_size > 0
        )
    except (OSError, ValueError):
        return False


def inspect_pending_files(db_path: Path, configured_download_dir: str, *,
                          project_root: Path = Path(".")) -> tuple[int, int]:
    """Check pending files after restart; return (valid, failed).

    Do not run concurrently with a live uploader. This does not delete files.
    """
    root = download_root(configured_download_dir, project_root)
    valid = failed = 0
    with database(db_path) as db:
        rows = db.execute(
            "SELECT id,ready_file FROM tasks WHERE status='upload_pending'"
        ).fetchall()
        for task_id, stored_path in rows:
            if stored_path and valid_ready_file(root, task_id, stored_path):
                valid += 1
            else:
                changed = db.execute(
                    """UPDATE tasks SET status='failed'
                    WHERE id=? AND status='upload_pending' AND ready_file IS ?""",
                    (task_id, stored_path),
                )
                failed += changed.rowcount
    return valid, failed
