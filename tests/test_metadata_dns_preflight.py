"""Fake-IP compatible metadata admission: URL validation and guarded process."""
import asyncio
import pytest
from bot import metadata_process

def fake_guard(command):
    return ["fake-sandbox", *command]

def test_fake_ip_dns_is_not_preflighted(monkeypatch):
    calls = []
    def forbidden(*args, **kwargs):
        raise AssertionError("DNS preflight must not run")
    monkeypatch.setattr("bot.network_security.validate_public_https_target", forbidden)
    async def runner(command, *, cwd, timeout_seconds):
        calls.append(command)
        return {"title": "ok"}
    monkeypatch.setattr(metadata_process, "run_json_subprocess", runner)
    result = asyncio.run(metadata_process.inspect_in_subprocess(
        "https://youtu.be/abc", timeout_seconds=5, network_guard=fake_guard))
    assert result["title"] == "ok"
    assert calls[0][0] == "fake-sandbox"

def test_unprotected_metadata_execution_fails_closed(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Must not execute")
    monkeypatch.setattr(metadata_process, "run_json_subprocess", forbidden)
    with pytest.raises(metadata_process.MetadataProcessError):
        asyncio.run(metadata_process.inspect_in_subprocess(
            "https://youtu.be/abc", timeout_seconds=5, network_guard=lambda c: c))
