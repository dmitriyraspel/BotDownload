"""Offline recovery sequence to run once before starting queue workers.

Caller must ensure no download or upload worker is running. This module
does not start downloads, uploads, or delete any files.
"""
from dataclasses import dataclass
from pathlib import Path

from .orphan_inventory import find_orphan_task_directories
from .ready_recovery import inspect_pending_files
from .storage import database, recover_interrupted_tasks
from .worker_recovery import reconcile_worker_leases


@dataclass(frozen=True)
class RecoveryReport:
    requeued: int
    ready_files: int
    missing_or_unsafe_files: int
    orphan_directories: tuple[Path, ...]


def recover_before_workers(
    db_path: Path,
    configured_download_dir: str,
    *,
    project_root: Path = Path("."),
) -> RecoveryReport:
    """Requeue interrupted work, validate uploads, inventory orphan directories.

    The caller must keep workers stopped for the entire operation.
    Orphans are reported but never removed automatically.
    """
    # Validate the configured mount before changing durable task states.
    from .download_storage import download_root

    download_root(configured_download_dir, project_root)
    with database(db_path) as db:
        # Leased jobs may still be active in a separately running worker.
        # Reconcile durable lease state first, then requeue only unleased work.
        reconcile_worker_leases(db)
        requeued = recover_interrupted_tasks(db)
    ready, failed = inspect_pending_files(
        db_path, configured_download_dir, project_root=project_root,
    )
    orphans = find_orphan_task_directories(
        db_path, configured_download_dir, project_root=project_root,
    )
    return RecoveryReport(
        requeued=requeued,
        ready_files=ready,
        missing_or_unsafe_files=failed,
        orphan_directories=tuple(orphans),
    )
