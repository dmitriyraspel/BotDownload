from datetime import datetime, timedelta, timezone

from bot.storage import change_status, create_task, database
from bot.upload_queue import next_due_upload


def test_due_upload_handles_mixed_timezone_offsets(tmp_path):
    db_path = tmp_path / "db.sqlite"
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=1, chat_id=2, message_id=3,
            callback_key="timezone", source_url="https://youtu.be/x",
            media_key="x", variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")
        assert change_status(db, task_id, "downloading", "processing")
        assert change_status(db, task_id, "processing", "upload_pending")

        # +05:00 local time can look lexically later even when UTC has passed.
        past = (datetime.now(timezone.utc) - timedelta(minutes=10)).astimezone(
            timezone(timedelta(hours=5))
        ).isoformat()
        db.execute(
            "UPDATE tasks SET next_upload_at=? WHERE id=?", (past, task_id),
        )
    assert next_due_upload(db_path) == task_id

    with database(db_path) as db:
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).astimezone(
            timezone(timedelta(hours=-5))
        ).isoformat()
        db.execute(
            "UPDATE tasks SET next_upload_at=? WHERE id=?", (future, task_id),
        )
    assert next_due_upload(db_path) is None
