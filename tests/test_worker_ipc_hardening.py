"""Strict IPC validation regression tests; no network or external services."""
import asyncio
import math
import os
from pathlib import Path

import pytest

from bot.worker_ipc import WorkerProtocolError, parse_request, ping, serve


@pytest.mark.parametrize("raw", [
    b'{"op":"ping","op":"ping","version":1}',
    b'{"op":"ping","version":1,"version":1}',
    b'{"op":"ping","version":1,"version":2}',
    b'{"op":"ping","version":1,"extra":0}',
    b'{"op":"ping","version":1} trailing',
    b'{"op":"ping","version":1}\xff',
])
def test_rejects_ambiguous_or_extra_json(raw):
    with pytest.raises(WorkerProtocolError):
        parse_request(raw)


@pytest.mark.parametrize("timeout", [None, True, False, 0, -1, float("inf"), float("nan"), "3"])
def test_ping_rejects_invalid_timeout_before_socket(tmp_path, timeout):
    assert not asyncio.run(ping(tmp_path / "missing.sock", timeout=timeout))


def test_serve_rejects_symlink_runtime_directory(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(WorkerProtocolError):
        asyncio.run(serve(link / "worker.sock", allowed_uid=os.getuid()))
    assert not (target / "worker.sock").exists()


def test_serve_rejects_world_writable_runtime_directory(tmp_path):
    directory = tmp_path / "runtime"
    directory.mkdir(mode=0o700)
    directory.chmod(0o777)
    try:
        with pytest.raises(WorkerProtocolError):
            asyncio.run(serve(directory / "worker.sock", allowed_uid=os.getuid()))
        assert not (directory / "worker.sock").exists()
    finally:
        directory.chmod(0o700)


@pytest.mark.parametrize("payload", [
    b'{"op":"ping","version":1}',
    b'{"op":"download","version":1}\\n',
    b'{"op":"ping","version":1,"version":1}\\n',
    b"x" * 5000 + b"\\n",
])
def test_worker_connection_rejects_bad_framing_and_commands(tmp_path, payload):
    from bot.worker_ipc import handle_connection

    async def run():
        path = tmp_path / "worker.sock"
        server = await asyncio.start_unix_server(
            lambda reader, writer: handle_connection(
                reader, writer, allowed_uid=os.getuid(),
            ),
            path=str(path), limit=4098,
        )
        try:
            reader, writer = await asyncio.open_unix_connection(str(path))
            writer.write(payload)
            await writer.drain()
            result = await asyncio.wait_for(reader.readline(), timeout=5)
            assert b'"status":"rejected"' in result
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())
