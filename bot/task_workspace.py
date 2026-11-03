"""Task-scoped storage lifecycle; deliberately does not start downloads."""
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .download_storage import (
    cleanup_task_directory,
    create_task_directory,
    download_root,
    require_free_space,
)


@contextmanager
def task_workspace(
    configured_path: str,
    task_id: str,
    expected_bytes: int,
    *,
    project_root: Path = Path("."),
    reserve_bytes: int = 512 * 1024 * 1024,
) -> Iterator[Path]:
    """Reserve a private workspace for a task and always clean it up.

    Free-space checks are advisory, not reservations. The future download
    worker must enforce byte limits while writing.
    """
    root = download_root(configured_path, project_root)
    require_free_space(root, expected_bytes, reserve_bytes=reserve_bytes)
    directory = create_task_directory(root, task_id)
    try:
        yield directory
    finally:
        cleanup_task_directory(root, directory)
