"""Offline dispatcher runs sequentially and stops without executing new work."""
import asyncio
from unittest.mock import patch

from bot.offline_dispatcher import run_offline_dispatcher


def test_dispatches_sequentially_and_stops(tmp_path):
    async def scenario():
        stop = asyncio.Event()
        active = 0
        seen = []
        async def process(**kwargs):
            nonlocal active
            active += 1
            assert active == 1
            seen.append(len(seen) + 1)
            await asyncio.sleep(0)
            active -= 1
            if len(seen) == 3:
                stop.set()
            return seen[-1]
        with patch("bot.offline_dispatcher.process_one_offline_task", side_effect=process):
            await asyncio.wait_for(run_offline_dispatcher(
                stop=stop, db_path=tmp_path / "db.sqlite",
                socket_path=tmp_path / "worker.sock",
                configured_download_dir="downloads",
            ), timeout=1)
        assert seen == [1, 2, 3]
    asyncio.run(scenario())


def test_idle_dispatcher_stops(tmp_path):
    async def scenario():
        stop = asyncio.Event()
        calls = 0
        async def process(**kwargs):
            nonlocal calls
            calls += 1
            return None
        with patch("bot.offline_dispatcher.process_one_offline_task", side_effect=process):
            task = asyncio.create_task(run_offline_dispatcher(
                stop=stop, db_path=tmp_path / "db.sqlite",
                socket_path=tmp_path / "worker.sock",
                configured_download_dir="downloads", idle_seconds=0.01,
            ))
            await asyncio.sleep(0.03)
            stop.set()
            await asyncio.wait_for(task, timeout=1)
        assert calls >= 1
    asyncio.run(scenario())
