"""Dedicated ping-only worker process; never run as root."""
import asyncio
import os
import pwd
from pathlib import Path
import sys

from .worker_ipc import serve


def main() -> None:
    if os.name != "posix" or os.geteuid() == 0:
        raise SystemExit("Worker должен работать без root")
    bot_user = os.environ.get("BOTDOWNLOAD_CLIENT_USER", "tgbot")
    if not bot_user or not bot_user.isascii():
        raise SystemExit("Неверный пользователь клиента")
    try:
        allowed_uid = pwd.getpwnam(bot_user).pw_uid
    except KeyError:
        raise SystemExit("Пользователь клиента не найден") from None
    socket_path = Path(os.environ.get(
        "BOTDOWNLOAD_WORKER_SOCKET", "/run/botdownload-worker/worker.sock",
    ))
    db_value = os.environ.get("BOTDOWNLOAD_WORKER_DB", "")
    db_path = Path(db_value) if db_value else None
    try:
        asyncio.run(serve(socket_path, allowed_uid=allowed_uid, db_path=db_path))
    except (OSError, ValueError) as exc:
        print(f"Worker не запущен: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
