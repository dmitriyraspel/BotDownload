"""Read-only inventory of ambiguous Telegram uploads.

An 'uploading' task may already have been delivered. Never auto-requeue,
delete its file, or release its quota reservation during reconciliation.
"""
import argparse
import json
from pathlib import Path

from .storage import database


def ambiguous_uploads(db_path: Path) -> list[dict]:
    """List unresolved uploads without exposing tokens or media URLs."""
    with database(db_path) as db:
        rows = db.execute(
            """SELECT t.id,t.user_id,t.chat_id,t.created_at,
                      t.upload_attempts,t.ready_file,
                      r.utc_day
               FROM tasks AS t
               LEFT JOIN delivery_reservations AS r ON r.task_id=t.id
               WHERE t.status='uploading'
               ORDER BY t.created_at,t.id"""
        ).fetchall()
    return [
        {"task_id": task_id, "user_id": user_id, "chat_id": chat_id,
         "created_at": created_at, "upload_attempts": attempts,
         "has_staged_file": bool(ready_file), "reserved_utc_day": utc_day}
        for task_id, user_id, chat_id, created_at, attempts, ready_file, utc_day in rows
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only report of ambiguous Telegram deliveries")
    parser.add_argument("--db", type=Path, required=True,
                        help="Path to existing SQLite state database")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.db.is_file():
        parser.error("SQLite database does not exist")
    records = ambiguous_uploads(args.db)
    if args.json:
        print(json.dumps({"ambiguous_uploads": records}, ensure_ascii=False))
    elif not records:
        print("Нет отправок с неопределённым результатом.")
    else:
        print(f"Неопределённых отправок: {len(records)}")
        for item in records:
            print(f"Задача {item['task_id']}: пользователь {item['user_id']}, "
                  f"попыток {item['upload_attempts']}, "
                  f"резерв UTC {item['reserved_utc_day'] or 'нет'}")
        print("Повторная отправка и освобождение лимита автоматически не выполняются.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
