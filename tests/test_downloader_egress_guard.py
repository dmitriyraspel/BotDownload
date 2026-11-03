"""Downloader must not execute yt-dlp without a distinct egress boundary."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from bot.downloader import DownloadError, download_to_temporary


def _download(**kwargs):
    return download_to_temporary(
        "https://youtu.be/abc", "mp3", duration=60,
        max_duration_seconds=120, max_bytes=100000,
        timeout_seconds=5, **kwargs)


def test_download_requires_egress_guard():
    with patch("bot.downloader.run_bounded_process", new_callable=AsyncMock) as runner:
        with pytest.raises(DownloadError, match="изоляция"):
            asyncio.run(_download())
        runner.assert_not_awaited()


@pytest.mark.parametrize("guard", [
    lambda cmd: cmd,
    lambda cmd: [],
    lambda cmd: ["wrapper", ""],
    lambda cmd: ["wrapper", chr(0)],
])
def test_download_rejects_missing_or_invalid_guard(guard):
    with patch("bot.downloader.run_bounded_process", new_callable=AsyncMock) as runner:
        with pytest.raises(DownloadError, match="изоляция"):
            asyncio.run(_download(network_guard=guard))
        runner.assert_not_awaited()


def test_guarded_command_is_passed_to_process_runner():
    async def fake_runner(command, **kwargs):
        assert command[0] == "sandbox-wrapper"
        assert "-m" in command
        raise RuntimeError("test stop")
    with patch("bot.downloader.run_bounded_process", side_effect=fake_runner):
        with pytest.raises(RuntimeError, match="test stop"):
            asyncio.run(_download(network_guard=lambda cmd: ["sandbox-wrapper", *cmd]))
