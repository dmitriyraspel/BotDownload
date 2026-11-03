"""Offline IPC protocol and kernel peer-credential regression tests."""
import asyncio
import json
import os
from pathlib import Path

import pytest

from bot import worker_ipc


@pytest.mark.parametrize("raw", [
    b"", b"null", b"[]", b"{}", b"not-json",
    b'{"op":"download","version":1}',
    b'{"op":"ping","version":2}',
    b'{"op":"ping","version":true}',
    b'{"op":"ping","version":1,"command":"sh"}',
    b'{"op":"ping"}',
    b"x" * (worker_ipc.MAX_MESSAGE + 1),
])
def test_protocol_rejects_invalid_requests(raw):
    with pytest.raises(worker_ipc.WorkerProtocolError):
        worker_ipc.parse_request(raw)


def test_protocol_accepts_only_ping():
    assert worker_ipc.parse_request(b'{"op":"ping","version":1}') == {
        "op": "ping", "version": 1,
    }


def test_worker_service_rejects_relative_socket(tmp_path):
    with pytest.raises(worker_ipc.WorkerProtocolError):
        asyncio.run(worker_ipc.serve(Path("worker.sock"), allowed_uid=os.getuid()))


def test_worker_service_rejects_invalid_uid(tmp_path):
    with pytest.raises(worker_ipc.WorkerProtocolError):
        asyncio.run(worker_ipc.serve(tmp_path / "worker.sock", allowed_uid=True))


def test_worker_service_refuses_existing_socket_path(tmp_path):
    path = tmp_path / "worker.sock"
    path.write_text("do not delete")
    with pytest.raises(worker_ipc.WorkerProtocolError):
        asyncio.run(worker_ipc.serve(path, allowed_uid=os.getuid()))
    assert path.read_text() == "do not delete"


def test_worker_ping_roundtrip_with_kernel_peer_credentials(tmp_path):
    async def run():
        path = tmp_path / "worker.sock"
        server = await asyncio.start_unix_server(
            lambda reader, writer: worker_ipc.handle_connection(
                reader, writer, allowed_uid=os.getuid(),
            ),
            path=str(path),
        )
        try:
            assert await worker_ipc.ping(path)
            reader, writer = await asyncio.open_unix_connection(str(path))
            writer.write(b'{"op":"download","version":1}\n')
            await writer.drain()
            result = json.loads(await reader.readline())
            assert result["status"] == "rejected"
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()
    asyncio.run(run())


def test_worker_rejects_wrong_kernel_uid(tmp_path):
    async def run():
        path = tmp_path / "worker.sock"
        server = await asyncio.start_unix_server(
            lambda reader, writer: worker_ipc.handle_connection(
                reader, writer, allowed_uid=os.getuid() + 100000,
            ),
            path=str(path),
        )
        try:
            assert not await worker_ipc.ping(path)
        finally:
            server.close()
            await server.wait_closed()
    asyncio.run(run())


def test_worker_ping_fails_closed_without_socket(tmp_path):
    assert not asyncio.run(worker_ipc.ping(tmp_path / "missing.sock"))
