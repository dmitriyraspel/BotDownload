"""Manual end-to-end Stage 2 smoke test. No Telegram delivery.

Usage:
  sudo -u tgbot .venv/bin/python -m bot.media_integration_smoke \
    --url 'https://www.youtube.com/watch?v=...' \
    --download-dir /absolute/private/downloads
"""
import argparse
import asyncio
import os
from pathlib import Path
import secrets
import tempfile

from .media_executor import validate_media_url
from .storage import database, create_task
from .worker_supervisor import OfflineWorkerSupervisor
from .media_queue_dispatcher import process_one_media_task


async def run(url: str, download_dir: str) -> int:
    validate_media_url(url)
    if os.geteuid() == 0:
        raise RuntimeError("Тест должен выполняться от tgbot, не root")
    root = Path(download_dir).resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise RuntimeError("Хранилище недоступно")
    with tempfile.TemporaryDirectory(prefix="botdownload-stage2-smoke-") as temp:
        db_path = Path(temp) / "test.sqlite"
        with database(db_path) as db:
            task_id, _ = create_task(
                db, user_id=1, chat_id=1, message_id=1,
                callback_key=secrets.token_hex(16), source_url=url,
                media_key="stage2-smoke", variant="video",
            )
        worker = OfflineWorkerSupervisor(db_path, media_root=str(root))
        socket = await worker.start()
        try:
            await process_one_media_task(
                db_path=db_path, socket_path=socket,
                configured_download_dir=str(root), lease_seconds=180,
            )
            with database(db_path) as db:
                row = db.execute(
                    "SELECT status,ready_file FROM tasks WHERE id=?", (task_id,),
                ).fetchone()
            print("Stage 2:", row[0])
            if row[0] == "upload_pending" and row[1] and Path(row[1]).is_file():
                print("Ready file:", row[1])
                print("Size:", Path(row[1]).stat().st_size)
                return 0
            return 1
        finally:
            await worker.stop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--download-dir", required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.url, args.download_dir)))


if __name__ == "__main__":
    main()
