"""In-memory, non-executing job reservation inside the isolated worker.

No media processing, subprocesses, filesystem paths or network calls.
The broker retains the only SQLite writer. Worker validates the broker's
capability against a read-only database before acknowledging it.
"""
import hashlib
import hmac
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


def valid_token(token: object) -> bool:
    return type(token) is str and len(token) == 64 and all(ch in "0123456789abcdef" for ch in token)


def verify_lease(db_path: Path | None, task_id: int, token: str) -> bool:
    if (not isinstance(db_path, Path) or not db_path.is_absolute()
            or type(task_id) is not int or not 0 < task_id <= 9223372036854775807
            or not valid_token(token)):
        return False
    try:
        uri = "file:" + quote(str(db_path), safe="/") + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=1)) as db:
            db.execute("PRAGMA query_only=ON")
            row = db.execute(
                """SELECT l.token_hash,l.state,l.expires_at,t.status
                FROM worker_job_leases AS l JOIN tasks AS t ON t.id=l.task_id
                WHERE l.task_id=?""", (task_id,),
            ).fetchone()
        if row is None or row[1] != "offered" or row[3] != "downloading":
            return False
        expiry = datetime.fromisoformat(row[2])
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            return False
        return hmac.compare_digest(row[0], hashlib.sha256(token.encode()).hexdigest())
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return False


class JobReservations:
    """At most one accepted job; reservations never execute media."""
    def __init__(self):
        self._active: tuple[int, str] | None = None

    def accept(self, db_path: Path | None, task_id: int, token: str) -> bool:
        if self._active is not None or not verify_lease(db_path, task_id, token):
            return False
        self._active = (task_id, hashlib.sha256(token.encode()).hexdigest())
        return True

    def cancel(self, task_id: int, token: str) -> bool:
        if not valid_token(token) or self._active is None:
            return False
        if (self._active[0] != task_id
                or not hmac.compare_digest(self._active[1], hashlib.sha256(token.encode()).hexdigest())):
            return False
        self._active = None
        return True

    def owns(self, task_id: int, token: str) -> bool:
        return (valid_token(token) and self._active is not None
                and self._active[0] == task_id
                and hmac.compare_digest(
                    self._active[1], hashlib.sha256(token.encode()).hexdigest()
                ))

    def clear(self) -> None:
        """Revoke all local reservations after an interrupted IPC session."""
        self._active = None
