"""Manual reconciliation must only record independently confirmed deliveries."""
import pytest

from bot.storage import (
    database, create_task, change_status, mark_file_ready,
    reserve_delivery_slot, count_daily_deliveries,
)
from bot.upload_reconciliation import confirm_delivered


def _uploading(db, key, *, reserve=True):
    task, _ = create_task(
        db, user_id=50, chat_id=50, message_id=50, callback_key=key,
        source_url="https://youtu.be/x", media_key="x", variant="MP3")
    assert change_status(db, task, "queued", "downloading")
    assert change_status(db, task, "downloading", "processing")
    assert mark_file_ready(db, task, "/staged/audio.mp3")
    if reserve:
        assert reserve_delivery_slot(db, task_id=task, utc_day="2026-11-03",
                                     daily_limit=3)
    assert change_status(db, task, "upload_pending", "uploading")
    return task


def test_operator_confirmed_delivery_is_idempotent(tmp_path):
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        task = _uploading(db, "first")
    assert confirm_delivered(path, task_id=task, telegram_file_id="confirmed-id")
    assert not confirm_delivered(path, task_id=task, telegram_file_id="confirmed-id")
    with database(path) as db:
        assert db.execute("SELECT status,telegram_file_id FROM tasks WHERE id=?",
                          (task,)).fetchone() == ("completed", "confirmed-id")
        assert count_daily_deliveries(db, user_id=50, utc_day="2026-11-03") == 1
        assert db.execute("SELECT COUNT(*) FROM delivery_reservations").fetchone()[0] == 0


def test_operator_cannot_complete_unreserved_upload(tmp_path):
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        task = _uploading(db, "unreserved", reserve=False)
    assert not confirm_delivered(path, task_id=task, telegram_file_id="id")
    with database(path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?",
                          (task,)).fetchone()[0] == "uploading"


def test_confirmation_rejects_empty_file_id(tmp_path):
    with pytest.raises(ValueError):
        confirm_delivered(tmp_path / "db.sqlite", task_id=1, telegram_file_id=" ")
