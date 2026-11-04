"""Opt-in real-worker SIGKILL/restart probe, isolated from production.

Requires Linux /proc, unprivileged UID, and an actual downloadable URL.
Never sends Telegram messages. An inconclusive run is not a pass.
"""
import argparse
import asyncio
import os
from pathlib import Path
import secrets
import signal
import tempfile

from .media_executor import validate_media_url
from .media_queue_dispatcher import process_one_media_task
from .storage import create_task, database, recover_interrupted_tasks
from .worker_leases import cancel_job
from .worker_supervisor import OfflineWorkerSupervisor


def descendants(parent: int) -> set[int]:
    """Snapshot recursive descendants using Linux /proc parent IDs."""
    pairs = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            fields = stat[stat.rfind(")") + 2:].split()
            pairs[int(entry.name)] = int(fields[1])
        except (OSError, ValueError, IndexError):
            continue
    found = set()
    frontier = {parent}
    while frontier:
        children = {pid for pid, ppid in pairs.items() if ppid in frontier}
        children -= found
        found.update(children)
        frontier = children
    return found


def alive(pid: int) -> bool:
    try:
        stat = (Path("/proc") / str(pid) / "stat").read_text()
        return stat[stat.rfind(")") + 2] != "Z"
    except (OSError, IndexError):
        return False


async def run(url: str, wait_seconds: float = 45) -> int:
    validate_media_url(url)
    if os.name != "posix" or not Path("/proc").is_dir() or os.geteuid() == 0:
        raise RuntimeError("Linux /proc and unprivileged UID required")
    if not 5 <= wait_seconds <= 120:
        raise ValueError("wait_seconds must be 5..120")
    with tempfile.TemporaryDirectory(prefix="botdownload-crash-probe-") as temporary:
        root = Path(temporary)
        media = root / "media"
        media.mkdir(mode=0o700)
        db_path = root / "isolated.sqlite"
        with database(db_path) as db:
            task_id, _ = create_task(
                db, user_id=1, chat_id=1, message_id=1,
                callback_key=secrets.token_hex(16), source_url=url,
                media_key="crash-probe", variant="video",
            )
        worker = OfflineWorkerSupervisor(db_path, media_root=str(media))
        socket = await worker.start()
        dispatch = asyncio.create_task(process_one_media_task(
            db_path=db_path, socket_path=socket,
            configured_download_dir=str(media), lease_seconds=180,
        ))
        child_pids = set()
        child_groups = set()
        crashed = False
        try:
            deadline = asyncio.get_running_loop().time() + wait_seconds
            while asyncio.get_running_loop().time() < deadline:
                pids = descendants(worker.process.pid)
                directories = [p for p in media.iterdir() if p.is_dir()]
                partials = [p for d in directories for p in d.iterdir()
                            if p.is_file() and p.name != ".namespace-stderr.log"]
                if partials and pids and not dispatch.done():
                    child_pids = pids
                    for pid in pids:
                        if alive(pid):
                            try:
                                child_groups.add(os.getpgid(pid))
                            except ProcessLookupError:
                                pass
                    break
                if dispatch.done():
                    break
                await asyncio.sleep(0.05)
            if not child_pids:
                print("INCONCLUSIVE: no active media subprocess with partial file")
                return 2
            # SIGKILL the worker PID, not its process group: simulate abrupt
            # process death and expose whether isolated children are orphaned.
            os.kill(worker.process.pid, signal.SIGKILL)
            await asyncio.wait_for(worker.process.wait(), timeout=5)
            crashed = True
            # Revoke the durable lease before recovery or any new worker.
            with database(db_path) as db:
                assert cancel_job(db, task_id)
                recover_interrupted_tasks(db)
            try:
                await asyncio.wait_for(dispatch, timeout=5)
            except (OSError, asyncio.TimeoutError):
                dispatch.cancel()
                try:
                    await dispatch
                except (asyncio.CancelledError, Exception):
                    pass
            await asyncio.sleep(0.5)
            orphans = sorted(pid for pid in child_pids if alive(pid))
            # Check before cleanup: a surviving child means this gate failed.
            if orphans:
                print("FAIL: orphaned media subprocess PIDs:", orphans)
                return 1
            # Restart the worker against the same private DB and assert no
            # lease resurrection or accidental publication.
            await worker.stop()
            worker = OfflineWorkerSupervisor(db_path, media_root=str(media))
            await worker.start()
            with database(db_path) as db:
                row = db.execute(
                    "SELECT status,ready_file,telegram_file_id FROM tasks WHERE id=?",
                    (task_id,),
                ).fetchone()
                lease = db.execute(
                    "SELECT state FROM worker_job_leases WHERE task_id=?",
                    (task_id,),
                ).fetchone()
            print("After restart:", row, "lease:", lease)
            if row[1:] != (None, None) or lease != ("cancelled",) or row[0] == "upload_pending":
                print("FAIL: publication or lease resurrection")
                return 1
            print("PASS: no orphan processes, no publication after worker restart")
            return 0
        finally:
            # Cleanup is intentionally separate from PASS/FAIL inspection.
            # Never signal arbitrary process groups: only those containing
            # subprocesses observed as descendants of our private worker.
            if crashed:
                for group in child_groups:
                    if group > 1 and group != os.getpgrp():
                        try:
                            os.killpg(group, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
            if not dispatch.done():
                dispatch.cancel()
                try:
                    await dispatch
                except (asyncio.CancelledError, Exception):
                    pass
            await worker.stop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--wait-seconds", type=float, default=45)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.url, args.wait_seconds)))


if __name__ == "__main__":
    main()
