"""Offline guard tests for the opt-in crash/restart probe."""
import asyncio
from unittest.mock import patch

import pytest

from bot.media_worker_crash_smoke import descendants, run


def test_descendants_does_not_include_self():
    import os
    assert os.getpid() not in descendants(os.getpid())


def test_crash_probe_refuses_root():
    with patch("bot.media_worker_crash_smoke.os.geteuid", return_value=0):
        with pytest.raises(RuntimeError, match="unprivileged"):
            asyncio.run(run("https://www.youtube.com/watch?v=jNQXAC9IVRw"))


@pytest.mark.parametrize("wait", [0, 4, 121])
def test_crash_probe_rejects_invalid_wait(wait):
    with patch("bot.media_worker_crash_smoke.os.geteuid", return_value=1001):
        with pytest.raises(ValueError, match="wait_seconds"):
            asyncio.run(run("https://www.youtube.com/watch?v=jNQXAC9IVRw", wait))


def test_crash_probe_refuses_loopback():
    with pytest.raises(Exception):
        asyncio.run(run("http://127.0.0.1/private"))
