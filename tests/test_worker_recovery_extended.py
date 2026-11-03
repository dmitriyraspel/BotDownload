"""Recovery tests for interrupted processing and broker cancellation."""
from bot.storage import change_status, create_task, database
from bot.worker_leases import offer_job
from bot.worker_recovery import reconcile_worker_leases


def test_expired_processing_lease_fails_task(tmp_path):
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        task_id, _ = create_task(
            db, user_id=1, chat_id=1, message_id=1,
            callback_key="expired-processing", source_url="https://example.com/",
            media_key="media", variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")
        assert offer_job(db, task_id)
        assert change_status(db, task_id, "downloading", "processing")
        db.execute(
            "UPDATE worker_job_leases SET expires_at=? WHERE task_id=?",
            ("2000-01-01T00:00:00+00:00", task_id),
        )
    with database(path) as db:
        assert reconcile_worker_leases(db) == {
            "expired": 1, "revoked": 0, "failed": 1,
        }
    with database(path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "failed"
        assert reconcile_worker_leases(db) == {
            "expired": 0, "revoked": 0, "failed": 0,
        }
