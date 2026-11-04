"""V1 supervisor lifecycle tests without Telegram or network."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from bot.worker_supervisor import OfflineWorkerSupervisor


def test_supervisor_rejects_double_start(tmp_path):
    async def scenario():
        supervisor = OfflineWorkerSupervisor(tmp_path / "bot.sqlite")
        supervisor.process = object()
        with pytest.raises(RuntimeError, match="уже запущен"):
            await supervisor.start()
    asyncio.run(scenario())


def test_supervisor_stop_without_start():
    async def scenario():
        supervisor = OfflineWorkerSupervisor(Path("data/bot.sqlite"))
        await supervisor.stop()
        assert supervisor.process is None
        assert supervisor.socket_path is None
    asyncio.run(scenario())


def test_supervisor_starts_and_stops_offline_ipc(tmp_path):
    import os
    if os.name != "posix" or os.geteuid() == 0:
        pytest.skip("Requires non-root POSIX runtime")

    async def scenario():
        from bot.database import initialize
        from bot.worker_ipc import ping

        db_path = tmp_path / "bot.sqlite"
        initialize(db_path)
        supervisor = OfflineWorkerSupervisor(db_path)
        socket = await supervisor.start()
        try:
            assert socket.is_socket()
            assert await ping(socket)
            assert supervisor.process.returncode is None
        finally:
            await supervisor.stop()
        assert not socket.exists()
    asyncio.run(scenario())
