"""Admission tests for opt-in resource-limit probe."""
import asyncio
from unittest.mock import patch

import pytest

from bot.media_resource_limits_smoke import run


def test_refuses_root():
    with patch("bot.media_resource_limits_smoke.os.geteuid", return_value=0):
        with pytest.raises(RuntimeError, match="unprivileged"):
            asyncio.run(run("https://www.youtube.com/watch?v=jNQXAC9IVRw"))


@pytest.mark.parametrize("seconds", [0, 11, -1, 1.5, True])
def test_refuses_invalid_timeout(seconds):
    with patch("bot.media_resource_limits_smoke.os.geteuid", return_value=1001):
        with pytest.raises(ValueError, match="timeout_seconds"):
            asyncio.run(run("https://www.youtube.com/watch?v=jNQXAC9IVRw",
                            timeout_seconds=seconds))


def test_refuses_loopback():
    with pytest.raises(Exception):
        asyncio.run(run("http://127.0.0.1/private"))
