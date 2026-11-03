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




def confirm_delivered(db_path: Path, *, task_id: int,
                      telegram_file_id: str) -> bool:
    """Operator-confirmed successful delivery, never a network retry.

    The operator must independently verify the Telegram message and file_id.
    Only a reserved, still-uploading task can be completed. This operation
    does not send a message or touch the staged file.
    """
    from .storage import complete_reserved_delivery
    if type(task_id) is not int or task_id <= 0:
        return False
    if not isinstance(telegram_file_id, str) or not telegram_file_id.strip():
        raise ValueError("Требуется подтверждённый Telegram file_id")
    with database(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        return complete_reserved_delivery(
            db, task_id=task_id, telegram_file_id=telegram_file_id
        )



def confirm_not_delivered(db_path: Path, *, task_id: int) -> bool:
    """Operator-verified non-delivery: make a quarantined task retryable.

    This must NEVER be used on a timeout alone. Confirm independently that
    Telegram did not accept the message. Preserve the staged file, release
    its reservation and reset its retry schedule in one SQLite transaction.
    """
    if type(task_id) is not int or task_id <= 0:
        return False
    with database(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """SELECT r.task_id FROM tasks AS t
               JOIN delivery_reservations AS r ON r.task_id=t.id
               WHERE t.id=? AND t.status='uploading'""",
            (task_id,),
        ).fetchone()
        if row is None:
            return False
        updated = db.execute(
            """UPDATE tasks SET status='upload_pending', next_upload_at=NULL,
                      upload_attempts=0
               WHERE id=? AND status='uploading'""",
            (task_id,),
        )
        if updated.rowcount != 1:
            raise RuntimeError("Не удалось вернуть задачу в ожидание отправки")
        deleted = db.execute(
            "DELETE FROM delivery_reservations WHERE task_id=?", (task_id,)
        )
        if deleted.rowcount != 1:
            raise RuntimeError("Не удалось освободить резерв отправки")
        return True

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
