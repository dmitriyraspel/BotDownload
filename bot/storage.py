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
    cursor = connection.execute(
        """UPDATE tasks SET status='queued' WHERE status IN ('downloading','processing')"""
    )
    connection.execute(
        "UPDATE tasks SET status='upload_pending' WHERE status='uploading'"
    )
    return cursor.rowcount
