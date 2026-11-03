"""Integration tests for non-executing broker-to-worker reservation IPC."""
import asyncio
import os

import pytest

from bot.storage import change_status, create_task, database
from bot.worker_dispatch import cancel_worker_reservation, reserve_worker_job
from bot.worker_ipc import WorkerProtocolError, handle_connection, parse_request
from bot.worker_leases import cancel_job, offer_job, transition_job
from bot.worker_reservations import JobReservations, verify_lease


def _offered(path, key):
    with database(path) as db:
        task, _ = create_task(
            db, user_id=1, chat_id=1, message_id=1, callback_key=key,
            source_url="https://example.com/", media_key="m", variant="video",
        )
        assert change_status(db, task, "queued", "downloading")
        token = offer_job(db, task)
    return task, token


def test_reservation_requires_valid_lease(tmp_path):
    db_path = tmp_path / "db.sqlite"
    task, token = _offered(db_path, "valid")
    assert verify_lease(db_path, task, token)
    assert not verify_lease(db_path, task, "0" * 64)
    assert not verify_lease(db_path, task + 1, token)
    assert not verify_lease(tmp_path / "missing.sqlite", task, token)


def test_worker_single_job_and_cancel(tmp_path):
    db_path = tmp_path / "db.sqlite"
    first, token1 = _offered(db_path, "first")
    second, token2 = _offered(db_path, "second")
    reservations = JobReservations()
    assert reservations.accept(db_path, first, token1)
    assert not reservations.accept(db_path, first, token1)
    assert not reservations.accept(db_path, second, token2)
    assert not reservations.cancel(first, token2)
    assert reservations.cancel(first, token1)
    assert not reservations.cancel(first, token1)
    assert reservations.accept(db_path, second, token2)


def test_revoked_and_expired_lease_cannot_be_reserved(tmp_path):
    db_path = tmp_path / "db.sqlite"
    task, token = _offered(db_path, "revoked")
    with database(db_path) as db:
        assert cancel_job(db, task)
    assert not JobReservations().accept(db_path, task, token)


@pytest.mark.parametrize("payload", [
    b'{"op":"reserve","version":1,"task_id":1}',
    b'{"op":"reserve","version":1,"task_id":1,"token":"wrong"}',
    b'{"op":"cancel_reservation","version":1,"task_id":true,"token":"' + b"0"*64 + b'"}',
    b'{"op":"reserve","version":1,"task_id":1,"token":"' + b"0"*64 + b'","argv":["sh"]}',
])
def test_protocol_rejects_unsafe_reservations(payload):
    with pytest.raises(WorkerProtocolError):
        parse_request(payload)


def test_reservation_ipc_roundtrip(tmp_path):
    db_path = tmp_path / "db.sqlite"
    task, token = _offered(db_path, "roundtrip")

    async def run():
        socket_path = tmp_path / "worker.sock"
        reservations = JobReservations()
        server = await asyncio.start_unix_server(
            lambda reader, writer: handle_connection(
                reader, writer, allowed_uid=os.getuid(),
                db_path=db_path, reservations=reservations,
            ), path=str(socket_path),
        )
        try:
            assert not await reserve_worker_job(socket_path, task, "0"*64)
            assert await reserve_worker_job(socket_path, task, token)
            assert not await reserve_worker_job(socket_path, task, token)
            with database(db_path) as db:
                assert transition_job(db, task, token, "offered", "running")
            assert not await cancel_worker_reservation(socket_path, task, "0"*64)
            assert await cancel_worker_reservation(socket_path, task, token)
            assert not await cancel_worker_reservation(socket_path, task, token)
        finally:
            server.close()
            await server.wait_closed()
    asyncio.run(run())


def test_reservation_ipc_unavailable_fails_closed(tmp_path):
    with pytest.raises(WorkerProtocolError):
        asyncio.run(reserve_worker_job(tmp_path / "missing.sock", 1, "0"*64))
