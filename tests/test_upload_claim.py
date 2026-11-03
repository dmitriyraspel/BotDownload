"""Upload claims cannot duplicate a possibly successful Telegram delivery."""
from bot.storage import (
    database, create_task, change_status, mark_file_ready,
    claim_upload_task, recover_interrupted_tasks, complete_reserved_delivery,
    count_daily_deliveries,
)


def _staged(db, key):
    task, _ = create_task(db, user_id=77, chat_id=77, message_id=77,
                          callback_key=key, source_url="https://youtu.be/x",
                          media_key="x", variant="MP3")
    assert change_status(db, task, "queued", "downloading")
    assert change_status(db, task, "downloading", "processing")
    assert mark_file_ready(db, task, "/private/staged.mp3")
    return task


def test_claim_requires_staged_file_and_is_idempotent(tmp_path):
    with database(tmp_path / "db.sqlite") as db:
        task, _ = create_task(db, user_id=77, chat_id=77, message_id=77,
                              callback_key="empty", source_url="https://youtu.be/x",
                              media_key="x", variant="MP3")
        assert not claim_upload_task(db, task_id=task, utc_day="2026-11-03",
                                     daily_limit=1)
        staged = _staged(db, "ready")
        assert claim_upload_task(db, task_id=staged, utc_day="2026-11-03",
                                 daily_limit=1)
        assert not claim_upload_task(db, task_id=staged, utc_day="2026-11-03",
                                     daily_limit=1)
        assert db.execute("SELECT status FROM tasks WHERE id=?",
                          (staged,)).fetchone()[0] == "uploading"


def test_crash_recovery_keeps_ambiguous_upload_quarantined(tmp_path):
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        staged = _staged(db, "ready")
        assert claim_upload_task(db, task_id=staged, utc_day="2026-11-03",
                                 daily_limit=1)
        queued, _ = create_task(db, user_id=88, chat_id=88, message_id=88,
                                callback_key="queued", source_url="https://youtu.be/x",
                                media_key="x", variant="MP3")
        assert change_status(db, queued, "queued", "downloading")
    with database(path) as db:
        assert recover_interrupted_tasks(db) == 1
        assert db.execute("SELECT status FROM tasks WHERE id=?",
                          (staged,)).fetchone()[0] == "uploading"
        assert db.execute("SELECT status FROM tasks WHERE id=?",
                          (queued,)).fetchone()[0] == "queued"
        assert complete_reserved_delivery(db, task_id=staged,
                                          telegram_file_id="telegram-id")
        assert count_daily_deliveries(db, user_id=77, utc_day="2026-11-03") == 1


def test_claim_enforces_quota_before_upload(tmp_path):
    with database(tmp_path / "db.sqlite") as db:
        first = _staged(db, "first")
        second = _staged(db, "second")
        assert claim_upload_task(db, task_id=first, utc_day="2026-11-03",
                                 daily_limit=1)
        assert not claim_upload_task(db, task_id=second, utc_day="2026-11-03",
                                     daily_limit=1)
        assert db.execute("SELECT status FROM tasks WHERE id=?",
                          (second,)).fetchone()[0] == "upload_pending"
