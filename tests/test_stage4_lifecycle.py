"""Integration tests for the polling/worker/background service lifecycle."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from bot.main import run_bot


class _Settings:
    token = "123456:FAKE"
    data = {
        "telegram": {"api_mode": "cloud", "max_upload_size_mb": {"cloud": 50}},
        "storage": {"download_dir": "downloads"},
        "telegram_upload_max_attempts": 3,
        "telegram_upload_second_attempt_delay_seconds": 1,
        "telegram_upload_third_attempt_delay_seconds": 2,
        "limits": {"daily_download_limit": 5},
        "trusted_users": [],
    }


class _Bot:
    def __init__(self, *args, **kwargs):
        self.session = type("Session", (), {"close": AsyncMock()})()


class _Worker:
    stopped = False

    def __init__(self, *args, **kwargs):
        self.exit = asyncio.Event()

    async def start(self):
        return None

    async def wait(self):
        await self.exit.wait()
        return 1

    async def stop(self):
        type(self).stopped = True
        self.exit.set()


def test_polling_exit_stops_background_services():
    async def scenario():
        stop_observed = []

        async def background(*, stop, **kwargs):
            await stop.wait()
            stop_observed.append(True)

        async def polling(*args, **kwargs):
            return None

        _Worker.stopped = False
        with patch("bot.main.Bot", _Bot), \
             patch("bot.main.OfflineWorkerSupervisor", _Worker), \
             patch("bot.main.run_upload_queue", side_effect=background), \
             patch("bot.main.run_queue_maintenance", side_effect=background), \
             patch("bot.main.Dispatcher") as dispatcher:
            dispatcher.return_value.start_polling.side_effect = polling
            await asyncio.wait_for(run_bot(_Settings()), timeout=2)
        assert _Worker.stopped
        assert len(stop_observed) == 2

    asyncio.run(scenario())


def test_background_failure_stops_worker():
    async def scenario():
        async def failing(*, stop, **kwargs):
            raise ValueError("background failed")

        async def waiting(*, stop, **kwargs):
            await stop.wait()

        async def polling(*args, **kwargs):
            await asyncio.Event().wait()

        _Worker.stopped = False
        with patch("bot.main.Bot", _Bot), \
             patch("bot.main.OfflineWorkerSupervisor", _Worker), \
             patch("bot.main.run_upload_queue", side_effect=waiting), \
             patch("bot.main.run_queue_maintenance", side_effect=failing), \
             patch("bot.main.Dispatcher") as dispatcher:
            dispatcher.return_value.start_polling.side_effect = polling
            with pytest.raises(RuntimeError, match="Queue maintenance"):
                await asyncio.wait_for(run_bot(_Settings()), timeout=2)
        assert _Worker.stopped

    asyncio.run(scenario())
