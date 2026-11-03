"""A metadata worker must never run without an explicit egress boundary."""
import asyncio

import pytest

from bot import metadata_process
from bot.metadata_process import MetadataProcessError


def test_metadata_worker_requires_network_guard(monkeypatch):
    invoked = []
    async def fake_runner(*args, **kwargs):
        invoked.append(args)
        return {}
    monkeypatch.setattr(metadata_process, "run_json_subprocess", fake_runner)
    with pytest.raises(MetadataProcessError, match="изоляция"):
        asyncio.run(metadata_process.inspect_in_subprocess(
            "https://youtu.be/abc", timeout_seconds=5,
        ))
    assert not invoked


def test_metadata_worker_rejects_noncallable_guard():
    with pytest.raises(MetadataProcessError, match="политика"):
        asyncio.run(metadata_process.inspect_in_subprocess(
            "https://youtu.be/abc", timeout_seconds=5, network_guard="unsafe",
        ))


def test_metadata_worker_wraps_command_after_preflight(monkeypatch):
    import bot.network_security as security
    monkeypatch.setattr(security, "validate_public_https_target",
                        lambda url, *, allowed_hosts: ("8.8.8.8",))
    received = []
    async def fake_runner(command, **kwargs):
        received.append(command)
        return {"title": "ok"}
    monkeypatch.setattr(metadata_process, "run_json_subprocess", fake_runner)
    result = asyncio.run(metadata_process.inspect_in_subprocess(
        "https://youtu.be/abc", timeout_seconds=5,
        network_guard=lambda command: ["guard", "--", *command],
    ))
    assert result == {"title": "ok"}
    assert received[0][:2] == ["guard", "--"]
    assert received[0][-2:] == ["bot.metadata_worker", "https://youtu.be/abc"]
