"""Only operator-verified non-delivery may unlock ambiguous uploads."""
from bot.storage import (
    database, create_task, change_status, mark_file_ready,
    reserve_delivery_slot,
)
from bot.upload_reconciliation import confirm_not_delivered


def _ambiguous(db, *, reserve=True):
    task, _ = create_task(
        db, user_id=41, chat_id=41, message_id=41,
        callback_key="ambiguous", source_url="https://youtu.be/x",
        media_key="x", variant="MP3")
    assert change_status(db, task, "queued", "downloading")
    assert change_status(db, task, "downloading", "processing")
    assert mark_file_ready(db, task, "/staged/audio.mp3")
    if reserve:
        assert reserve_delivery_slot(db, task_id=task, utc_day="2026-11-03",
                                     daily_limit=3)
    assert change_status(db, task, "upload_pending", "uploading")
    return task


def test_verified_non_delivery_releases_reservation_and_allows_retry(tmp_path):
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        task = _ambiguous(db)
        db.execute("UPDATE tasks SET upload_attempts=2 WHERE id=?", (task,))
    assert confirm_not_delivered(path, task_id=task)
    assert not confirm_not_delivered(path, task_id=task)
    with database(path) as db:
        assert db.execute(
            "SELECT status,upload_attempts,next_upload_at,ready_file FROM tasks WHERE id=?",
            (task,)
        ).fetchone() == ("upload_pending", 0, None, "/staged/audio.mp3")
        assert db.execute(
            "SELECT COUNT(*) FROM delivery_reservations WHERE task_id=?",
            (task,)
        ).fetchone()[0] == 0


def test_non_delivery_refuses_unreserved_task(tmp_path):
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        task = _ambiguous(db, reserve=False)
    assert not confirm_not_delivered(path, task_id=task)
    with database(path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?",
                          (task,)).fetchone()[0] == "uploading"


def test_non_delivery_refuses_invalid_task_id(tmp_path):
    assert not confirm_not_delivered(tmp_path / "db.sqlite", task_id=0)
