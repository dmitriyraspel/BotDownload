import pytest

from bot.storage import (
    database, enqueue_task, claim_next_task, change_status,
    recover_interrupted_tasks,
)


def _enqueue(db, key, *, max_pending=20):
    return enqueue_task(
        db, max_pending=max_pending, user_id=1, chat_id=1,
        message_id=int(key), callback_key=key,
        source_url="https://youtu.be/abc", media_key="youtube:abc",
        variant="720p",
    )


def test_queue_capacity_and_duplicate(tmp_path):
    with database(tmp_path / "queue.sqlite") as db:
        first, created = _enqueue(db, "1", max_pending=2)
        assert created
        same, created = _enqueue(db, "1", max_pending=2)
        assert same == first and not created
        _enqueue(db, "2", max_pending=2)
        with pytest.raises(OverflowError):
            _enqueue(db, "3", max_pending=2)


def test_single_active_worker_and_fifo(tmp_path):
    with database(tmp_path / "queue.sqlite") as db:
        first, _ = _enqueue(db, "1")
        second, _ = _enqueue(db, "2")
        assert claim_next_task(db, max_wait_minutes=30) == first
        assert claim_next_task(db, max_wait_minutes=30) is None
        assert change_status(db, first, "downloading", "processing")
        assert claim_next_task(db, max_wait_minutes=30) is None
        assert change_status(db, first, "processing", "upload_pending")
        assert claim_next_task(db, max_wait_minutes=30) == second


def test_expired_queue_items(tmp_path):
    with database(tmp_path / "queue.sqlite") as db:
        old, _ = _enqueue(db, "1")
        db.execute(
            "UPDATE tasks SET created_at='2020-01-01T00:00:00.000Z' WHERE id=?",
            (old,),
        )
        fresh, _ = _enqueue(db, "2")
        assert claim_next_task(db, max_wait_minutes=30) == fresh
        assert db.execute(
            "SELECT status FROM tasks WHERE id=?", (old,)
        ).fetchone()[0] == "failed"


def test_restart_recovers_interrupted_jobs(tmp_path):
    with database(tmp_path / "queue.sqlite") as db:
        a, _ = _enqueue(db, "1")
        b, _ = _enqueue(db, "2")
        assert change_status(db, a, "queued", "downloading")
        assert change_status(db, b, "queued", "downloading")
        assert change_status(db, b, "downloading", "processing")
        assert recover_interrupted_tasks(db) == 2
        assert db.execute(
            "SELECT status FROM tasks WHERE id=?", (a,)
        ).fetchone()[0] == "queued"
        assert db.execute(
            "SELECT status FROM tasks WHERE id=?", (b,)
        ).fetchone()[0] == "queued"
