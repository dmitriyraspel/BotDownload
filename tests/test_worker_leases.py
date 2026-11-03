"""Broker lease state machine tests, entirely offline."""
from datetime import datetime, timedelta, timezone

import pytest

from bot.storage import create_task, database, change_status
from bot.worker_leases import offer_job, transition_job, cancel_job, expire_jobs


def _task(db, key):
    task_id, _ = create_task(
        db, user_id=1, chat_id=1, message_id=1,
        callback_key=key, source_url="https://example.com/",
        media_key="m", variant="video",
    )
    return task_id


def test_offer_requires_claimed_task(tmp_path):
    with database(tmp_path / "db.sqlite") as db:
        task = _task(db, "offer")
        assert offer_job(db, task) is None
        assert change_status(db, task, "queued", "downloading")
        token = offer_job(db, task)
        assert len(token) == 64
        assert offer_job(db, task) is None


def test_lease_cas_and_no_replay(tmp_path):
    with database(tmp_path / "db.sqlite") as db:
        task = _task(db, "cas")
        change_status(db, task, "queued", "downloading")
        token = offer_job(db, task)
        assert not transition_job(db, task, "0" * 64, "offered", "running")
        assert transition_job(db, task, token, "offered", "running")
        assert not transition_job(db, task, token, "offered", "running")
        assert transition_job(db, task, token, "running", "finished")
        assert not transition_job(db, task, token, "running", "finished")


def test_cancel_revokes_lease(tmp_path):
    with database(tmp_path / "db.sqlite") as db:
        task = _task(db, "cancel")
        change_status(db, task, "queued", "downloading")
        token = offer_job(db, task)
        assert cancel_job(db, task)
        assert not cancel_job(db, task)
        assert not transition_job(db, task, token, "offered", "running")


def test_expire_prevents_start(tmp_path):
    with database(tmp_path / "db.sqlite") as db:
        task = _task(db, "expire")
        change_status(db, task, "queued", "downloading")
        token = offer_job(db, task)
        db.execute(
            "UPDATE worker_job_leases SET expires_at=? WHERE task_id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), task),
        )
        assert expire_jobs(db) == 1
        assert expire_jobs(db) == 0
        assert not transition_job(db, task, token, "offered", "running")


def test_cancelled_task_cannot_start(tmp_path):
    with database(tmp_path / "db.sqlite") as db:
        task = _task(db, "task-cancel")
        change_status(db, task, "queued", "downloading")
        token = offer_job(db, task)
        change_status(db, task, "downloading", "cancelled")
        assert not transition_job(db, task, token, "offered", "running")


@pytest.mark.parametrize("value", [None, True, 0, -1, "1", 2**63])
def test_offer_rejects_invalid_id(tmp_path, value):
    with database(tmp_path / "db.sqlite") as db:
        with pytest.raises(ValueError):
            offer_job(db, value)


@pytest.mark.parametrize("ttl", [None, True, 0, -1, 3601, 1.5])
def test_offer_rejects_invalid_ttl(tmp_path, ttl):
    with database(tmp_path / "db.sqlite") as db:
        with pytest.raises(ValueError):
            offer_job(db, 1, ttl_seconds=ttl)
