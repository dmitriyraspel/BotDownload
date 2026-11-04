"""No-network tests for namespace runner admission and fail-closed behavior."""
import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.media_executor import UnsafeMediaRequest
from bot.media_isolated_runner import execute_isolated
from bot.media_namespace_entry import entry_command


def test_entry_rejects_missing_gateway(tmp_path):
    with pytest.raises(UnsafeMediaRequest):
        entry_command(
            "https://www.youtube.com/watch?v=abcdefghijk",
            tmp_path / "absent.sock", timeout_seconds=10, max_bytes=1024,
        )


def test_entry_rejects_internal_url(tmp_path):
    with pytest.raises(UnsafeMediaRequest):
        entry_command(
            "http://127.0.0.1/private",
            tmp_path / "absent.sock", timeout_seconds=10, max_bytes=1024,
        )


def test_cancel_before_spawn(tmp_path):
    async def scenario():
        gateway = tmp_path / "gateway.sock"
        import socket
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(gateway))
            event = asyncio.Event()
            event.set()
            with patch("bot.media_namespace_entry.shutil.which", return_value="/usr/bin/unshare"):
                with pytest.raises(asyncio.CancelledError):
                    await execute_isolated(
                        "https://www.youtube.com/watch?v=abcdefghijk",
                        gateway=gateway, workspace=tmp_path,
                        timeout_seconds=10, max_bytes=1024, cancel=event,
                    )
    asyncio.run(scenario())
