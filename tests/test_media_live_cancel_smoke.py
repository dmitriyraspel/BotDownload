"""Offline admission tests for the opt-in live cancellation probe."""
import asyncio
from unittest.mock import patch

import pytest

from bot.media_live_cancel_smoke import run


def test_rejects_root_before_creating_worker():
    with patch("bot.media_live_cancel_smoke.os.geteuid", return_value=0):
        with pytest.raises(RuntimeError, match="unprivileged"):
            asyncio.run(run("https://www.youtube.com/watch?v=abcdefghijk"))


@pytest.mark.parametrize("seconds", [0, 4, 121])
def test_rejects_invalid_wait(seconds):
    with patch("bot.media_live_cancel_smoke.os.geteuid", return_value=1001):
        with pytest.raises(ValueError, match="wait_seconds"):
            asyncio.run(run("https://www.youtube.com/watch?v=abcdefghijk",
                            wait_seconds=seconds))


def test_rejects_loopback_url_before_starting_worker():
    with pytest.raises(Exception):
        asyncio.run(run("http://127.0.0.1/private"))
