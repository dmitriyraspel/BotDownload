"""Opt-in live worker cancellation acceptance probe; no Telegram delivery.

Run only as unprivileged tgbot. Uses a private temporary SQLite database and
media directory; never touches the configured production download directory.
"""
import argparse
import asyncio
import os
from pathlib import Path
import secrets
import tempfile

from .media_executor import validate_media_url
from .media_queue_dispatcher import process_one_media_task
from .storage import cancel_task, create_task, database
from .worker_supervisor import OfflineWorkerSupervisor


async def run(url: str, *, wait_seconds: float = 45) -> int:
    validate_media_url(url)
    if os.name != "posix" or os.geteuid() == 0:
        raise RuntimeError("Run as an unprivileged user, never root")
    if not 5 <= wait_seconds <= 120:
        raise ValueError("wait_seconds must be 5..120")
    with tempfile.TemporaryDirectory(prefix="botdownload-live-cancel-") as temporary:
        root = Path(temporary)
        media_root = root / "media"
        media_root.mkdir(mode=0o700)
        db_path = root / "isolated.sqlite"
        with database(db_path) as db:
            task_id, _ = create_task(
                db, user_id=1, chat_id=1, message_id=1,
                callback_key=secrets.token_hex(16), source_url=url,
                media_key="live-cancel-smoke", variant="video",
            )
        supervisor = OfflineWorkerSupervisor(db_path, media_root=str(media_root))
        socket_path = await supervisor.start()
        dispatch = None
        try:
            dispatch = asyncio.create_task(process_one_media_task(
                db_path=db_path, socket_path=socket_path,
                configured_download_dir=str(media_root), lease_seconds=180,
            ))
            loop = asyncio.get_running_loop()
            deadline = loop.time() + wait_seconds
            observed = False
            while loop.time() < deadline:
                with database(db_path) as db:
                    status = db.execute(
                        "SELECT status FROM tasks WHERE id=?", (task_id,)
                    ).fetchone()[0]
                # Wait for the actual namespace process to begin writing a
                # partial media file, not merely for a claimed queue entry.
                dirs = [p for p in media_root.iterdir() if p.is_dir()]
                partials = [
                    p for directory in dirs for p in directory.iterdir()
                    if p.is_file() and p.name != ".namespace-stderr.log"
                ]
                if status == "downloading" and partials and not dispatch.done():
                    observed = True
                    break
                if dispatch.done() or status != "downloading" and status != "queued":
                    break
                await asyncio.sleep(0.05)
            if not observed:
                print("INCONCLUSIVE: no active partial download observed before completion/timeout")
                return 2
            with database(db_path) as db:
                if not cancel_task(db, task_id=task_id, user_id=1):
                    print("INCONCLUSIVE: task finished before cancellation")
                    return 2
            await asyncio.wait_for(dispatch, timeout=15)
            # Allow worker's lease watcher and cleanup to finish; dispatcher
            # can return before the separate worker has cleaned its workspace.
            for _ in range(100):
                if not list(media_root.iterdir()):
                    break
                await asyncio.sleep(0.05)
            with database(db_path) as db:
                row = db.execute(
                    "SELECT status,ready_file,telegram_file_id FROM tasks WHERE id=?",
                    (task_id,),
                ).fetchone()
            remaining = [str(p.relative_to(media_root)) for p in media_root.rglob("*")]
            print("Task:", row[0], "ready_file:", row[1],
                  "telegram_file_id:", row[2], "remaining:", remaining)
            if row == ("cancelled", None, None) and not remaining:
                print("PASS: live worker cancellation, no staged file, workspace cleaned")
                return 0
            print("FAIL: cancellation left a published result or workspace")
            return 1
        finally:
            if dispatch is not None and not dispatch.done():
                dispatch.cancel()
                try:
                    await dispatch
                except asyncio.CancelledError:
                    pass
            await supervisor.stop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--wait-seconds", type=float, default=45)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.url, wait_seconds=args.wait_seconds)))


if __name__ == "__main__":
    main()
