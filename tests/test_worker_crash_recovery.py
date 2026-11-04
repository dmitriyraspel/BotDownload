"""Worker crash reconciliation never replays a leased job."""
from bot.storage import create_task, database, change_status
from bot.worker_leases import offer_job, transition_job
from bot.worker_crash_recovery import reconcile_confirmed_worker_exit


def test_worker_exit_revokes_active_and_preserves_unrelated(tmp_path):
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        active, _ = create_task(
            db, user_id=1, chat_id=1, message_id=1,
            callback_key="active", source_url="https://youtu.be/x",
            media_key="x", variant="MP3",
        )
        pending, _ = create_task(
            db, user_id=1, chat_id=1, message_id=2,
            callback_key="pending", source_url="https://youtu.be/y",
            media_key="y", variant="MP3",
        )
        assert change_status(db, active, "queued", "downloading")
        token = offer_job(db, active)
        assert token
        assert transition_job(db, active, token, "offered", "running")
    assert reconcile_confirmed_worker_exit(path) == 1
    assert reconcile_confirmed_worker_exit(path) == 0
    with database(path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?", (active,)).fetchone()[0] == "failed"
        assert db.execute("SELECT status FROM tasks WHERE id=?", (pending,)).fetchone()[0] == "queued"
        assert db.execute("SELECT state FROM worker_job_leases WHERE task_id=?", (active,)).fetchone()[0] == "cancelled"
        assert not transition_job(db, active, token, "running", "finished")


def test_worker_exit_without_leases_is_noop(tmp_path):
    assert reconcile_confirmed_worker_exit(tmp_path / "empty.sqlite") == 0
