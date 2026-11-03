"""DNS preflight remains defense in depth in the isolated metadata path."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from bot import metadata_process
from bot.network_security import UnsafeNetworkTarget


def fake_egress_guard(command):
    """Only for mocked process execution, never production confinement."""
    return ["fake-sandbox", *command]


def test_metadata_rejects_unsafe_dns_before_extraction(monkeypatch):
    invoked = []

    def unsafe(url, *, allowed_hosts):
        raise UnsafeNetworkTarget("private")

    async def fake_runner(*args, **kwargs):
        invoked.append("spawn")
        return {"title": "unexpected"}

    monkeypatch.setattr(metadata_process, "validate_public_https_target", unsafe, raising=False)
    monkeypatch.setattr(metadata_process, "run_json_subprocess", fake_runner)
    # The isolated transport imports the validator directly from network_security.
    monkeypatch.setattr("bot.network_security.validate_public_https_target", unsafe)
    with pytest.raises(UnsafeNetworkTarget):
        asyncio.run(metadata_process.inspect_in_subprocess(
            "https://youtu.be/abc", timeout_seconds=5,
            network_guard=fake_egress_guard,
        ))
    assert invoked == []


def test_metadata_allows_preflight_then_invokes_guarded_process(monkeypatch):
    seen = []

    def public(url, *, allowed_hosts):
        seen.append(("dns", url))
        return ("8.8.8.8",)

    async def fake_runner(command, *, cwd, timeout_seconds):
        seen.append(("process", command[0]))
        assert command[0] == "fake-sandbox"
        assert timeout_seconds == 5
        return {"title": "test"}

    monkeypatch.setattr("bot.network_security.validate_public_https_target", public)
    monkeypatch.setattr(metadata_process, "run_json_subprocess", fake_runner)
    result = asyncio.run(metadata_process.inspect_in_subprocess(
        "https://youtu.be/abc", timeout_seconds=5,
        network_guard=fake_egress_guard,
    ))
    assert result["title"] == "test"
    assert seen == [
        ("dns", "https://youtu.be/abc"),
        ("process", "fake-sandbox"),
    ]
