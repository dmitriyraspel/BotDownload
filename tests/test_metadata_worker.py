"""Offline tests for the metadata subprocess CLI and orchestration."""
import asyncio
import json

import pytest

from bot import metadata_process, metadata_worker


def test_worker_rejects_invalid_url(capsys):
    assert metadata_worker.main(["http://127.0.0.1/"]) == 2
    assert capsys.readouterr().out == ""


def test_worker_serializes_extracted_data(monkeypatch, capsys):
    monkeypatch.setattr(metadata_worker, "validate_public_https_target", lambda url, *, allowed_hosts: ("8.8.8.8",))
    monkeypatch.setattr(metadata_worker, "_extract", lambda url: {"title": "Привет"})
    assert metadata_worker.main(["https://youtu.be/abc"]) == 0
    assert json.loads(capsys.readouterr().out) == {"title": "Привет"}


def test_worker_hides_extractor_errors(monkeypatch, capsys):
    def fail(url):
        raise RuntimeError("secret URL token")
    monkeypatch.setattr(metadata_worker, "validate_public_https_target", lambda url, *, allowed_hosts: ("8.8.8.8",))
    monkeypatch.setattr(metadata_worker, "_extract", fail)
    assert metadata_worker.main(["https://youtu.be/abc"]) == 1
    assert capsys.readouterr().out == ""


def test_inspection_preflight_blocks_process(monkeypatch):
    calls = []

    def unsafe(url, *, allowed_hosts):
        raise ValueError("blocked")

    import bot.network_security as ns
    monkeypatch.setattr(ns, "validate_public_https_target", unsafe)

    async def fake_runner(*args, **kwargs):
        calls.append(args)
        return {}

    monkeypatch.setattr(metadata_process, "run_json_subprocess", fake_runner)
    with pytest.raises(ValueError, match="blocked"):
        asyncio.run(metadata_process.inspect_in_subprocess(
            "https://youtu.be/abc", timeout_seconds=3,
            network_guard=lambda command: command,
        ))
    assert calls == []
