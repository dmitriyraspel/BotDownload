"""Cancellation and crash recovery are fail-closed for offline worker leases."""
from datetime import datetime, timedelta, timezone

from bot.storage import create_task, database, cancel_task, change_status
from bot.worker_leases import offer_job, transition_job
from bot.worker_recovery import reconcile_worker_leases
from bot.startup_recovery import recover_before_workers


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
