"""Regression checks: untrusted metadata cannot run in bot process."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from bot.metadata import AnalysisError, inspect


def test_metadata_fails_closed_without_network_boundary():
    with patch("bot.metadata._extract") as extract:
        with pytest.raises(AnalysisError, match="изоляция"):
            asyncio.run(inspect("https://youtu.be/abc"))
        extract.assert_not_called()


def test_metadata_uses_cancellable_process_transport():
    async def fake_inspect(url, *, timeout_seconds, network_guard):
        assert url == "https://youtu.be/abc"
        assert timeout_seconds == 7
        assert network_guard is guard
        return {"title": "safe"}
    def guard(command):
        return ["sandbox", *command]
    with patch("bot.metadata_process.inspect_in_subprocess", side_effect=fake_inspect):
        assert asyncio.run(inspect("https://youtu.be/abc", timeout=7, network_guard=guard)) == {"title": "safe"}


def test_metadata_rejects_invalid_url_before_spawning():
    with patch("bot.metadata_process.inspect_in_subprocess", new_callable=AsyncMock) as runner:
        with pytest.raises(AnalysisError, match="Недопустимая"):
            asyncio.run(inspect("http://127.0.0.1/"))
        runner.assert_not_awaited()
