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


def test_namespace_timeout_has_dedicated_exit_status():
    from bot.media_namespace_bridge import _main
    with patch("bot.media_namespace_bridge.run_download",
               side_effect=asyncio.TimeoutError):
        with pytest.raises(SystemExit) as exc:
            asyncio.run(_main(None, ["fixture"], 1))
    assert exc.value.code == 124


def test_namespace_normal_error_is_not_timeout():
    from bot.media_namespace_bridge import _main
    with patch("bot.media_namespace_bridge.run_download", return_value=1):
        with pytest.raises(SystemExit) as exc:
            asyncio.run(_main(None, ["fixture"], 1))
    assert exc.value.code == 1
