"""Explicit, conservative cleanup of orphan task directories.

Only invoke while all workers are stopped. No automatic deletion at startup.
A candidate must be an exact path returned by an earlier orphan inventory;
the directory and SQLite references are rechecked immediately before cleanup.
"""
import os
from pathlib import Path
import re
import stat

from .download_storage import download_root
from .storage import database

_TASK_DIR = re.compile(r"task-([1-9][0-9]*)-[0-9a-f]{32}\Z")


def remove_orphan_task_directory(
    db_path: Path, configured_download_dir: str, candidate: Path, *,
    project_root: Path = Path("."),
) -> bool:
    """Delete only an unreferenced private task dir containing <=1 regular file.

    Returns False if the candidate is missing, registered, or not safely owned.
    Never follows symlinks and never removes unexpected nested contents.
    Requires exclusive access to the bot's storage and database.
    """
    root = download_root(configured_download_dir, project_root)
    candidate = Path(candidate)
    if candidate.parent != root or _TASK_DIR.fullmatch(candidate.name) is None:
        return False
    try:
        if candidate.is_symlink():
            return False
        info = candidate.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            return False
        entries = list(candidate.iterdir())
        if len(entries) > 1:
            return False
        if entries:
            file = entries[0]
            if file.is_symlink():
                return False
            st = file.lstat()
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                    or st.st_nlink != 1):
                return False
    except OSError:
        return False

    with database(db_path) as db:
        # A reference from any status, including terminal tasks, blocks deletion.
        references = db.execute(
            "SELECT ready_file FROM tasks WHERE ready_file IS NOT NULL"
        ).fetchall()
        if any(
            isinstance(row[0], str) and Path(row[0]).parent == candidate
            for row in references
        ):
            return False
        try:
            if entries:
                entries[0].unlink()
            candidate.rmdir()
        except OSError:
            return False
    return True
