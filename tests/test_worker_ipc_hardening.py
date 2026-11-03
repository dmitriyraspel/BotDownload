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
