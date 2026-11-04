"""Cancellation and crash recovery are fail-closed for offline worker leases."""
from datetime import datetime, timedelta, timezone

from bot.storage import create_task, database, cancel_task, change_status
from bot.worker_leases import offer_job, transition_job
from bot.worker_recovery import reconcile_worker_leases


def _leased(db):
    task, _ = create_task(
        db, user_id=10, chat_id=10, message_id=10,
        callback_key="cancel-case", source_url="https://youtu.be/x",
        media_key="x", variant="MP3",
    )
    assert change_status(db, task, "queued", "downloading")
    token = offer_job(db, task)
    assert token
    assert transition_job(db, task, token, "offered", "running")
    return task, token


def test_cancel_revokes_lease_in_same_transaction(tmp_path):
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        task, token = _leased(db)
        assert not cancel_task(db, task_id=task, user_id=11)
        assert cancel_task(db, task_id=task, user_id=10)
        assert not cancel_task(db, task_id=task, user_id=10)
        assert not transition_job(db, task, token, "running", "finished")
        assert db.execute("SELECT state FROM worker_job_leases WHERE task_id=?", (task,)).fetchone()[0] == "cancelled"
        assert db.execute("SELECT status FROM tasks WHERE id=?", (task,)).fetchone()[0] == "cancelled"


def test_crashed_leased_task_fails_without_requeue(tmp_path):
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        task, token = _leased(db)
        db.execute("UPDATE worker_job_leases SET expires_at=? WHERE task_id=?", (
            (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), task,
        ))
    with database(path) as db:
        report = reconcile_worker_leases(db)
        assert report["expired"] == 1
        assert report["failed"] == 1
        assert db.execute("SELECT status FROM tasks WHERE id=?", (task,)).fetchone()[0] == "failed"
        assert not transition_job(db, task, token, "running", "finished")
        assert reconcile_worker_leases(db)["failed"] == 0


def test_bulk_cancel_revokes_only_owned_work(tmp_path):
    from bot.storage import cancel_user_tasks
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        task, token = _leased(db)
        other, _ = create_task(
            db, user_id=20, chat_id=20, message_id=20,
            callback_key="other", source_url="https://youtu.be/y",
            media_key="y", variant="MP3",
        )
        assert cancel_user_tasks(db, 10) == 1
        assert cancel_user_tasks(db, 10) == 0
        assert db.execute("SELECT status FROM tasks WHERE id=?", (task,)).fetchone()[0] == "cancelled"
        assert db.execute("SELECT state FROM worker_job_leases WHERE task_id=?", (task,)).fetchone()[0] == "cancelled"
        assert db.execute("SELECT status FROM tasks WHERE id=?", (other,)).fetchone()[0] == "queued"
        assert not transition_job(db, task, token, "running", "finished")


def test_cancel_pending_task_never_claimed(tmp_path):
    from bot.storage import claim_next_task
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        task, _ = create_task(
            db, user_id=10, chat_id=10, message_id=10,
            callback_key="pending", source_url="https://youtu.be/x",
            media_key="x", variant="MP3",
        )
        assert cancel_task(db, task_id=task, user_id=10)
        assert claim_next_task(db, max_wait_minutes=30) is None
