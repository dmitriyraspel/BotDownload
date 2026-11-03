"""Regression checks for downloader process lifetime management.

The downloader is not activated in Telegram. These tests use a fake process
runner and never access the network.
"""
import asyncio
from pathlib import Path

import pytest

from bot import downloader
from bot.process_runner import ProcessExecutionError


def test_download_uses_bounded_process_runner(monkeypatch):
    seen = []

    async def fake_runner(argv, *, cwd, timeout_seconds):
        seen.append((argv, cwd, timeout_seconds))
        (cwd / "result.mp3").write_bytes(b"audio")

    monkeypatch.setattr(downloader, "run_bounded_process", fake_runner)
    monkeypatch.setattr(downloader, "build_command", lambda url, mode, max_bytes, output: ["fake", url])
    temporary, result = asyncio.run(downloader.download_to_temporary(
        "https://example.org/video", "mp3", duration=20,
        max_duration_seconds=60, max_bytes=100, timeout_seconds=5,
    ))
    try:
        assert result.read_bytes() == b"audio"
        assert len(seen) == 1
        assert seen[0][2] == 5
        assert seen[0][1] == result.parent
    finally:
        temporary.cleanup()


def test_download_failure_cleans_temporary_directory(monkeypatch):
    directories = []

    async def fake_runner(argv, *, cwd, timeout_seconds):
        directories.append(cwd)
        raise ProcessExecutionError("timeout")

    monkeypatch.setattr(downloader, "run_bounded_process", fake_runner)
    monkeypatch.setattr(downloader, "build_command", lambda url, mode, max_bytes, output: ["fake"])
    with pytest.raises(downloader.DownloadError):
        asyncio.run(downloader.download_to_temporary(
            "https://example.org/video", "mp3", duration=20,
            max_duration_seconds=60, max_bytes=100, timeout_seconds=5,
        ))
    assert len(directories) == 1
    assert not directories[0].exists()


def test_download_cancellation_propagates_and_cleans(monkeypatch):
    directories = []

    async def fake_runner(argv, *, cwd, timeout_seconds):
        directories.append(cwd)
        raise asyncio.CancelledError()

    monkeypatch.setattr(downloader, "run_bounded_process", fake_runner)
    monkeypatch.setattr(downloader, "build_command", lambda url, mode, max_bytes, output: ["fake"])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(downloader.download_to_temporary(
            "https://example.org/video", "mp3", duration=20,
            max_duration_seconds=60, max_bytes=100, timeout_seconds=5,
        ))
    assert not directories[0].exists()
