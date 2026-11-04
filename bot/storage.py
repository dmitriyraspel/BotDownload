"""SQLite foundation for durable, idempotent task state.

No downloads are started by this module. Runtime wiring follows separately.
"""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS previews (
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL CHECK(user_id > 0),
    source_url TEXT NOT NULL,
    media_key TEXT NOT NULL,
    available_variants TEXT NOT NULL,
    cancelled INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(chat_id,message_id)
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL CHECK(user_id > 0),
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    callback_key TEXT NOT NULL UNIQUE,
    source_url TEXT NOT NULL,
    media_key TEXT NOT NULL,
    variant TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK(status IN ('queued','downloading','processing','upload_pending',
                         'uploading','completed','failed','cancelled')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    download_attempts INTEGER NOT NULL DEFAULT 0,
    upload_attempts INTEGER NOT NULL DEFAULT 0,
    next_upload_at TEXT,
    status_message_id INTEGER,
    ready_file TEXT,
    telegram_file_id TEXT
);
CREATE INDEX IF NOT EXISTS tasks_queue_idx ON tasks(status, created_at, id);
CREATE INDEX IF NOT EXISTS tasks_user_idx ON tasks(user_id, status);
CREATE TABLE IF NOT EXISTS cache (
    media_key TEXT NOT NULL,
    variant TEXT NOT NULL,
    audio_track TEXT NOT NULL,
    processing_options TEXT NOT NULL,
    telegram_file_id TEXT NOT NULL,
    valid INTEGER NOT NULL DEFAULT 1 CHECK(valid IN (0,1)),
    PRIMARY KEY(media_key,variant,audio_track,processing_options)
);
CREATE TABLE IF NOT EXISTS daily_usage (
    user_id INTEGER NOT NULL,
    utc_day TEXT NOT NULL,
    task_id INTEGER NOT NULL UNIQUE REFERENCES tasks(id),
    PRIMARY KEY(user_id,utc_day,task_id)
);
CREATE TABLE IF NOT EXISTS delivery_reservations (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id),
    user_id INTEGER NOT NULL,
    utc_day TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS delivery_reservations_user_day_idx
    ON delivery_reservations(user_id, utc_day);
CREATE TABLE IF NOT EXISTS link_attempts (
    user_id INTEGER NOT NULL,
    attempted_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS link_attempts_idx ON link_attempts(user_id,attempted_at);
CREATE TABLE IF NOT EXISTS bans (
    user_id INTEGER PRIMARY KEY,
    banned_until INTEGER NOT NULL
);
"""


@contextmanager
def database(path: Path) -> Iterator[sqlite3.Connection]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.executescript(SCHEMA)
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def create_task(connection: sqlite3.Connection, *, user_id: int, chat_id: int,
                message_id: int, callback_key: str, source_url: str,
                media_key: str, variant: str) -> tuple[int, bool]:
    """Returns (task_id, newly_created). Duplicate callback is harmless."""
    if user_id <= 0 or not callback_key:
        raise ValueError("Некорректный пользователь или ключ действия")
    cursor = connection.execute(
        """INSERT OR IGNORE INTO tasks
        (user_id,chat_id,message_id,callback_key,source_url,media_key,variant)
        VALUES (?,?,?,?,?,?,?)""",
        (user_id,chat_id,message_id,callback_key,source_url,media_key,variant),
    )
    row = connection.execute(
        "SELECT id,user_id FROM tasks WHERE callback_key=?", (callback_key,)
    ).fetchone()
    if row is None or row[1] != user_id:
        raise ValueError("Действие принадлежит другому пользователю")
    return row[0], cursor.rowcount == 1


def change_status(connection: sqlite3.Connection, task_id: int,
                  from_status: str, to_status: str) -> bool:
    allowed = {
        "queued": {"downloading", "cancelled", "failed"},
        "downloading": {"processing", "failed", "cancelled", "queued"},
        "processing": {"upload_pending", "failed", "cancelled", "queued"},
        "upload_pending": {"uploading", "cancelled", "failed"},
        "uploading": {"completed", "upload_pending", "cancelled", "failed"},
    }
    if to_status not in allowed.get(from_status, set()):
        return False
    cursor = connection.execute(
        "UPDATE tasks SET status=? WHERE id=? AND status=?",
        (to_status,task_id,from_status),
    )
    return cursor.rowcount == 1


def cancel_user_tasks(connection: sqlite3.Connection, user_id: int) -> int:
    """Only cancel nonterminal tasks owned by this Telegram user."""
    cursor = connection.execute(
        """UPDATE tasks SET status='cancelled' WHERE user_id=?
        AND status IN ('queued','downloading','processing','upload_pending','uploading')""",
        (user_id,),
    )
    return cursor.rowcount


def record_delivery(connection: sqlite3.Connection, task_id: int,
                    telegram_file_id: str, utc_day: str, *, cache_hit: bool) -> bool:
    """Atomically mark uploaded task and charge quota at most once."""
    if not telegram_file_id:
        raise ValueError("Пустой Telegram file_id")
    cursor = connection.execute(
        """UPDATE tasks SET status='completed', telegram_file_id=?
        WHERE id=? AND status='uploading'""",
        (telegram_file_id,task_id),
    )
    if cursor.rowcount != 1:
        return False
    if not cache_hit:
        connection.execute(
            """INSERT OR IGNORE INTO daily_usage(user_id,utc_day,task_id)
            SELECT user_id,?,id FROM tasks WHERE id=?""",
            (utc_day,task_id),
        )
    return True


def save_preview(connection: sqlite3.Connection, *, chat_id: int, message_id: int,
                 user_id: int, source_url: str, media_key: str,
                 variants: list[str]) -> None:
    import json
    if user_id <= 0 or not variants:
        raise ValueError("Некорректное превью")
    connection.execute(
        """INSERT INTO previews
        (chat_id,message_id,user_id,source_url,media_key,available_variants)
        VALUES (?,?,?,?,?,?)""",
        (chat_id,message_id,user_id,source_url,media_key,json.dumps(variants)),
    )


def select_preview(connection: sqlite3.Connection, *, chat_id: int,
                   message_id: int, user_id: int, variant: str) -> tuple[str,str] | None:
    import json
    row = connection.execute(
        """SELECT source_url,media_key,available_variants FROM previews
        WHERE chat_id=? AND message_id=? AND user_id=? AND cancelled=0""",
        (chat_id,message_id,user_id),
    ).fetchone()
    if row is None or variant not in json.loads(row[2]):
        return None
    return row[0], row[1]


def cancel_preview_record(connection: sqlite3.Connection, *, chat_id: int,
                          message_id: int, user_id: int) -> bool:
    cursor = connection.execute(
        """UPDATE previews SET cancelled=1 WHERE chat_id=? AND message_id=?
        AND user_id=? AND cancelled=0""",
        (chat_id,message_id,user_id),
    )
    return cursor.rowcount == 1


def existing_preview_task(connection: sqlite3.Connection, *, chat_id: int, message_id: int) -> tuple[int, str] | None:
    """A preview can create only one task, regardless of chosen format."""
    row = connection.execute(
        "SELECT id,variant FROM tasks WHERE chat_id=? AND message_id=? ORDER BY id LIMIT 1",
        (chat_id, message_id),
    ).fetchone()
    return (row[0], row[1]) if row else None


def enqueue_task(connection: sqlite3.Connection, *, max_pending: int, **kwargs) -> tuple[int, bool]:
    """Queue a task if capacity permits; duplicate callback never uses a slot."""
    if max_pending <= 0:
        raise ValueError("max_pending должен быть положительным")
    if not connection.in_transaction:
        connection.execute("BEGIN IMMEDIATE")
    existing = connection.execute(
        "SELECT id,user_id FROM tasks WHERE callback_key=?", (kwargs["callback_key"],)
    ).fetchone()
    if existing:
        if existing[1] != kwargs["user_id"]:
            raise ValueError("Действие принадлежит другому пользователю")
        return existing[0], False
    existing_card = existing_preview_task(
        connection, chat_id=kwargs["chat_id"], message_id=kwargs["message_id"]
    )
    if existing_card:
        owner = connection.execute("SELECT user_id FROM tasks WHERE id=?", (existing_card[0],)).fetchone()[0]
        if owner != kwargs["user_id"]:
            raise ValueError("Задача принадлежит другому пользователю")
        return existing_card[0], False
    pending = connection.execute(
        "SELECT COUNT(*) FROM tasks WHERE status='queued'"
    ).fetchone()[0]
    if pending >= max_pending:
        raise OverflowError("Очередь заполнена")
    return create_task(connection, **kwargs)


def claim_next_task(connection: sqlite3.Connection, *, max_wait_minutes: int) -> int | None:
    """Claim oldest eligible queued task; expire tasks that waited too long."""
    if max_wait_minutes <= 0:
        raise ValueError("max_wait_minutes должен быть положительным")
    if not connection.in_transaction:
        connection.execute("BEGIN IMMEDIATE")
    connection.execute(
        """UPDATE tasks SET status='failed' WHERE status='queued'
        AND created_at < strftime('%Y-%m-%dT%H:%M:%fZ','now', ?)""",
        (f"-{max_wait_minutes} minutes",),
    )
    active = connection.execute(
        "SELECT COUNT(*) FROM tasks WHERE status IN ('downloading','processing')"
    ).fetchone()[0]
    if active:
        return None
    row = connection.execute(
        "SELECT id FROM tasks WHERE status='queued' ORDER BY created_at,id LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    task_id = row[0]
    if not change_status(connection, task_id, "queued", "downloading"):
        return None
    return task_id


def recover_interrupted_tasks(connection: sqlite3.Connection) -> int:
    """Restore interrupted downloads to the queue; preserve upload retries."""
    # Jobs ever dispatched to the separate worker must not be replayed:
    # the worker may still be executing after only the bot process restarts.
    # Lease reconciliation handles these jobs separately, without retrying.
    lease_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='worker_job_leases'"
    ).fetchone() is not None
    if lease_table:
        cursor = connection.execute(
            """UPDATE tasks SET status='queued'
            WHERE status IN ('downloading','processing')
            AND NOT EXISTS (
                SELECT 1 FROM worker_job_leases l WHERE l.task_id=tasks.id
            )"""
        )
    else:
        cursor = connection.execute(
            """UPDATE tasks SET status='queued'
            WHERE status IN ('downloading','processing')"""
        )
    # Upload outcome may be ambiguous after a crash. Do not retry
    # 'uploading' automatically: Telegram may already have delivered it.
    # An operator/reconciliation path must resolve such tasks explicitly.
    return cursor.rowcount


def cancel_task(connection: sqlite3.Connection, *, task_id: int, user_id: int) -> bool:
    """Atomically cancel owned work and revoke any active worker lease."""
    if type(task_id) is not int or type(user_id) is not int or task_id <= 0 or user_id <= 0:
        return False
    if not connection.in_transaction:
        connection.execute("BEGIN IMMEDIATE")
    cursor = connection.execute(
        """UPDATE tasks SET status='cancelled'
        WHERE id=? AND user_id=?
        AND status IN ('queued','downloading','processing','upload_pending')""",
        (task_id, user_id),
    )
    if cursor.rowcount != 1:
        return False
    from .worker_leases import cancel_job
    cancel_job(connection, task_id)
    return True


def task_is_cancelled(connection: sqlite3.Connection, task_id: int) -> bool:
    """Allow the worker to poll for cancellation between processing steps."""
    row = connection.execute(
        "SELECT status FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    return row is not None and row[0] == "cancelled"


def mark_file_ready(connection: sqlite3.Connection, task_id: int, ready_file: str) -> bool:
    """Atomically publish a prepared file path only from processing state.

    The caller must have staged the file in a bot-owned private directory.
    This method never opens, deletes, or trusts the file path itself.
    """
    if type(task_id) is not int or task_id <= 0:
        return False
    if not isinstance(ready_file, str) or not ready_file.strip() or "\x00" in ready_file:
        raise ValueError("Некорректный путь готового файла")
    cursor = connection.execute(
        """UPDATE tasks SET ready_file=?, status='upload_pending'
        WHERE id=? AND status='processing' AND ready_file IS NULL""",
        (ready_file, task_id),
    )
    return cursor.rowcount == 1


def get_pending_file(connection: sqlite3.Connection, task_id: int) -> str | None:
    """Retrieve a staged path only for an upload-pending task."""
    row = connection.execute(
        """SELECT ready_file FROM tasks
        WHERE id=? AND status='upload_pending' AND ready_file IS NOT NULL""",
        (task_id,),
    ).fetchone()
    return row[0] if row else None



def get_task(connection: sqlite3.Connection, task_id: int) -> dict | None:
    """Read the persisted work item without exposing arbitrary SQL to workers."""
    if type(task_id) is not int or task_id <= 0:
        return None
    previous_factory = connection.row_factory
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """SELECT id,user_id,chat_id,message_id,source_url,media_key,
                      variant,status,created_at,download_attempts,
                      upload_attempts,ready_file,telegram_file_id
               FROM tasks WHERE id=?""", (task_id,)
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        connection.row_factory = previous_factory


def count_daily_deliveries(connection: sqlite3.Connection, *,
                           user_id: int, utc_day: str) -> int:
    """Count charged successful deliveries, excluding cache hits."""
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("Некорректный Telegram ID")
    from datetime import date
    try:
        if date.fromisoformat(utc_day).isoformat() != utc_day:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("Некорректная UTC-дата") from exc
    return connection.execute(
        "SELECT COUNT(*) FROM daily_usage WHERE user_id=? AND utc_day=?",
        (user_id, utc_day)
    ).fetchone()[0]


def quota_available(connection: sqlite3.Connection, *, user_id: int,
                    utc_day: str, daily_limit: int,
                    trusted_users: tuple[int, ...] | list[int] = ()) -> bool:
    """A preflight hint; the delivery path must recheck quota atomically."""
    if type(daily_limit) is not int or daily_limit <= 0:
        raise ValueError("Некорректный дневной лимит")
    used = count_daily_deliveries(connection, user_id=user_id, utc_day=utc_day)
    return user_id in trusted_users or used < daily_limit


def reserve_delivery_slot(connection: sqlite3.Connection, *, task_id: int,
                          utc_day: str, daily_limit: int,
                          trusted_users: tuple[int, ...] | list[int] = ()) -> bool:
    """Reserve quota before Telegram upload; atomic across SQLite connections.

    Returns False if the task is ineligible or the quota is exhausted.
    Reservations are per-task and idempotent. Call release_delivery_slot
    after a failed upload; finalize via complete_reserved_delivery only
    after Telegram confirms delivery.
    """
    if type(task_id) is not int or task_id <= 0:
        return False
    if type(daily_limit) is not int or daily_limit <= 0:
        raise ValueError("Некорректный дневной лимит")
    from datetime import date
    try:
        if date.fromisoformat(utc_day).isoformat() != utc_day:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("Некорректная UTC-дата") from exc
    if not connection.in_transaction:
        connection.execute("BEGIN IMMEDIATE")
    row = connection.execute(
        "SELECT user_id,status FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    if row is None or row[1] != "upload_pending":
        return False
    user_id = row[0]
    existing = connection.execute(
        "SELECT utc_day FROM delivery_reservations WHERE task_id=?", (task_id,)
    ).fetchone()
    if existing is not None:
        return existing[0] == utc_day
    if user_id not in trusted_users:
        used = count_daily_deliveries(connection, user_id=user_id, utc_day=utc_day)
        reserved = connection.execute(
            """SELECT COUNT(*) FROM delivery_reservations
            WHERE user_id=? AND utc_day=?""", (user_id, utc_day)
        ).fetchone()[0]
        if used + reserved >= daily_limit:
            return False
    connection.execute(
        """INSERT INTO delivery_reservations(task_id,user_id,utc_day)
        VALUES (?,?,?)""", (task_id, user_id, utc_day)
    )
    return True


def release_delivery_slot(connection: sqlite3.Connection, task_id: int) -> bool:
    """Release a reservation after a confirmed non-delivery."""
    return connection.execute(
        "DELETE FROM delivery_reservations WHERE task_id=?", (task_id,)
    ).rowcount == 1


def complete_reserved_delivery(connection: sqlite3.Connection, *,
                               task_id: int, telegram_file_id: str,
                               cache_hit: bool = False) -> bool:
    """Finalize a reserved, confirmed Telegram delivery exactly once.

    Caller must use a transaction; record_delivery and reservation deletion
    happen together. Do not release reservations after ambiguous upload errors
    without first resolving whether Telegram accepted the message.
    """
    row = connection.execute(
        "SELECT utc_day FROM delivery_reservations WHERE task_id=?", (task_id,)
    ).fetchone()
    if row is None:
        return False
    if not record_delivery(connection, task_id, telegram_file_id, row[0],
                           cache_hit=cache_hit):
        return False
    connection.execute("DELETE FROM delivery_reservations WHERE task_id=?",
                       (task_id,))
    return True



def claim_upload_task(connection: sqlite3.Connection, *, task_id: int,
                      utc_day: str, daily_limit: int,
                      trusted_users: tuple[int, ...] | list[int] = ()) -> bool:
    """Atomically reserve quota and transition a staged task to uploading.

    Commit the surrounding database context before sending anything to Telegram.
    A crashed or ambiguous upload stays in 'uploading' for reconciliation.
    """
    if not connection.in_transaction:
        connection.execute("BEGIN IMMEDIATE")
    row = connection.execute(
        "SELECT ready_file FROM tasks WHERE id=? AND status='upload_pending'",
        (task_id,)
    ).fetchone()
    if row is None or not row[0]:
        return False
    if not reserve_delivery_slot(connection, task_id=task_id, utc_day=utc_day,
                                 daily_limit=daily_limit,
                                 trusted_users=trusted_users):
        return False
    if not change_status(connection, task_id, "upload_pending", "uploading"):
        raise RuntimeError("Не удалось зарезервировать отправку")
    return True
