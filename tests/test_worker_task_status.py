"""Task ID IPC and read-only SQLite integration tests."""
import asyncio
import json
import os

import pytest

from bot.storage import create_task, database
from bot.worker_client import query_task_status
from bot.worker_ipc import WorkerProtocolError, handle_connection, parse_request, task_status


@pytest.mark.parametrize("task_id", [None, True, 0, -1, 1.5, "1", 2**63])
def test_task_status_request_rejects_invalid_ids(task_id):
    raw = json.dumps({"op": "task_status", "version": 1, "task_id": task_id}).encode()
    with pytest.raises(WorkerProtocolError):
        parse_request(raw)


def test_task_status_request_accepts_numeric_id():
    assert parse_request(b'{"op":"task_status","version":1,"task_id":42}')["task_id"] == 42


def test_task_status_sqlite_read_only(tmp_path):
    path = tmp_path / "bot.sqlite"
    with database(path) as db:
        task_id, created = create_task(
            db, user_id=1, chat_id=1, message_id=1,
            callback_key="ipc-1", source_url="https://example.com/",
            media_key="m", variant="video",
        )
    assert created
    assert task_status(path, task_id) == "queued"
    assert task_status(path, task_id + 1000) == "missing"
    assert task_status(tmp_path / "absent.sqlite", task_id) == "unavailable"
    with database(path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "queued"


def test_task_status_ipc_roundtrip(tmp_path):
    db_path = tmp_path / "bot.sqlite"
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=1, chat_id=1, message_id=1,
            callback_key="ipc-2", source_url="https://example.com/",
            media_key="m", variant="video",
        )

    async def run():
        path = tmp_path / "worker.sock"
        server = await asyncio.start_unix_server(
            lambda reader, writer: handle_connection(
                reader, writer, allowed_uid=os.getuid(), db_path=db_path,
            ), path=str(path),
        )
        try:
            assert await query_task_status(path, task_id) == "queued"
            assert await query_task_status(path, task_id + 1) == "missing"
        finally:
            server.close()
            await server.wait_closed()
    asyncio.run(run())


def test_task_status_ipc_rejects_other_uid(tmp_path):
    async def run():
        path = tmp_path / "worker.sock"
        server = await asyncio.start_unix_server(
            lambda reader, writer: handle_connection(
                reader, writer, allowed_uid=os.getuid() + 100000,
            ), path=str(path),
        )
        try:
            with pytest.raises(WorkerProtocolError):
                await query_task_status(path, 1)
        finally:
            server.close()
            await server.wait_closed()
    asyncio.run(run())


def test_task_status_ipc_missing_worker_fails_closed(tmp_path):
    with pytest.raises(WorkerProtocolError):
        asyncio.run(query_task_status(tmp_path / "missing.sock", 1))
