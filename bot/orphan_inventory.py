"""Read-only inventory of private task directories after a worker shutdown.

Never delete unregistered directories automatically: a live worker or a
crash before SQLite publication can produce an identical directory.
Call only with workers stopped and inspect reported paths before cleanup.
"""
from pathlib import Path
import os
import re
import stat

from .download_storage import download_root
from .storage import database

_TASK_DIR = re.compile(r"task-([1-9][0-9]*)-[0-9a-f]{32}\Z")


def find_orphan_task_directories(
    db_path: Path, configured_download_dir: str, *,
    project_root: Path = Path("."),
) -> list[Path]:
    """List owned, private, unreferenced task directories without modifying them."""
    root = download_root(configured_download_dir, project_root)
    with database(db_path) as db:
        references = {
            row[0] for row in db.execute(
                "SELECT ready_file FROM tasks WHERE ready_file IS NOT NULL"
            ) if isinstance(row[0], str)
        }
    referenced_dirs = {str(Path(path).parent) for path in references}
    orphans = []
    for folder in root.iterdir():
        match = _TASK_DIR.fullmatch(folder.name)
        if match is None or folder.is_symlink():
            continue
        try:
            info = folder.lstat()
            if (not stat.S_ISDIR(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_mode & 0o077):
                continue
        except OSError:
            continue
        if str(folder) not in referenced_dirs:
            orphans.append(folder)
    return sorted(orphans)
