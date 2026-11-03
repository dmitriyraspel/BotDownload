"""Broker IPC handshake tests; no media execution or external network."""
import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.storage import change_status, create_task, database
from bot.worker_broker import reserve_claimed_task, revoke_claimed_task
from bot.worker_ipc import WorkerProtocolError


def claimed(tmp_path):
    path = tmp_path / "tasks.sqlite"
    with database(path) as db:
        task_id, _ = create_task(
            db, user_id=1, chat_id=1, message_id=1,
            callback_key="broker-task", source_url="https://example.com/",
            media_key="media", variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")
    return path, task_id


def state(path, task_id):
    with database(path) as db:
        return db.execute(
            "SELECT state FROM worker_job_leases WHERE task_id=?", (task_id,)
        ).fetchone()[0]


def test_accepted_reservation_transitions_to_running(tmp_path):
    path, task_id = claimed(tmp_path)

    async def accepted(*args, **kwargs):
        return True

    with patch("bot.worker_broker.reserve_worker_job", accepted):
        assert asyncio.run(reserve_claimed_task(
            db_path=path, socket_path=Path("/tmp/offline.sock"), task_id=task_id
        ))
    assert state(path, task_id) == "running"
    assert asyncio.run(revoke_claimed_task(
        db_path=path, socket_path=Path("/tmp/offline.sock"), task_id=task_id
    ))
    assert state(path, task_id) == "cancelled"


def test_rejected_reservation_revokes_durable_lease(tmp_path):
    path, task_id = claimed(tmp_path)

    async def rejected(*args, **kwargs):
        return False

    with (patch("bot.worker_broker.reserve_worker_job", rejected),
          patch("bot.worker_broker.cancel_worker_reservation", rejected)):
        assert not asyncio.run(reserve_claimed_task(
            db_path=path, socket_path=Path("/tmp/offline.sock"), task_id=task_id
        ))
    assert state(path, task_id) == "cancelled"


def test_uncertain_ipc_error_revokes_durable_lease(tmp_path):
    path, task_id = claimed(tmp_path)

    async def unavailable(*args, **kwargs):
        raise WorkerProtocolError("offline")

    with (patch("bot.worker_broker.reserve_worker_job", unavailable),
          patch("bot.worker_broker.cancel_worker_reservation", unavailable)):
        with pytest.raises(WorkerProtocolError):
            asyncio.run(reserve_claimed_task(
                db_path=path, socket_path=Path("/tmp/offline.sock"), task_id=task_id
            ))
    assert state(path, task_id) == "cancelled"


def test_unclaimed_task_is_not_reserved(tmp_path):
    path = tmp_path / "tasks.sqlite"
    with database(path) as db:
        task_id, _ = create_task(
            db, user_id=1, chat_id=1, message_id=1,
            callback_key="unclaimed", source_url="https://example.com/",
            media_key="media", variant="480p",
        )
    assert not asyncio.run(reserve_claimed_task(
        db_path=path, socket_path=Path("/tmp/offline.sock"), task_id=task_id
    ))


def test_task_cancelled_during_ipc_cannot_become_running(tmp_path):
    path, task_id = claimed(tmp_path)

    async def cancel_during_reservation(*args, **kwargs):
        with database(path) as db:
            assert change_status(db, task_id, "downloading", "cancelled")
        return True

    async def cancelled(*args, **kwargs):
        return True

    with (patch("bot.worker_broker.reserve_worker_job", cancel_during_reservation),
          patch("bot.worker_broker.cancel_worker_reservation", cancelled)):
        assert not asyncio.run(reserve_claimed_task(
            db_path=path, socket_path=Path("/tmp/offline.sock"), task_id=task_id
        ))
    assert state(path, task_id) == "cancelled"
