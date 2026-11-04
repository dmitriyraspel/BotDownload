"""Stage 2 active cancellation: real process groups and media ownership, offline."""
import asyncio
import os
from pathlib import Path
import signal
import socket
import sys
from unittest.mock import patch

import pytest

from bot.media_isolated_runner import execute_isolated
from bot.worker_media import MediaJobController


def test_media_cancel_only_active_owned_job():
    async def scenario():
        controller = MediaJobController(None)
        event = asyncio.Event()
        controller._busy = True
        controller._active_job = (42, "owned-token")
        controller._cancel_event = event
        assert not controller.cancel(43, "owned-token")
        assert not controller.cancel(42, "other-token")
        assert not event.is_set()
        assert controller.cancel(42, "owned-token")
        assert event.is_set()
    asyncio.run(scenario())


def test_active_cancel_kills_isolated_process_group(tmp_path):
    """Fake entry command spawns a real child; cancellation kills the group."""
    async def scenario():
        gateway = tmp_path / "gateway.sock"
        workspace = tmp_path / "work"
        workspace.mkdir()
        with socket.socket(socket.AF_UNIX) as sock:
            sock.bind(str(gateway))
            # Parent and child both sleep; child writes a PID file.
            code = (
                "import subprocess,sys,time,pathlib;"
                "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
                "pathlib.Path(sys.argv[1]).write_text(str(p.pid));"
                "time.sleep(60)"
            )
            child_file = tmp_path / "child.pid"
            event = asyncio.Event()
            with patch("bot.media_namespace_entry.entry_command",
                       return_value=[sys.executable, "-c", code, str(child_file)]):
                task = asyncio.create_task(execute_isolated(
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    gateway=gateway, workspace=workspace,
                    timeout_seconds=10, max_bytes=1024, cancel=event,
                ))
                try:
                    for _ in range(100):
                        if child_file.exists():
                            break
                        await asyncio.sleep(0.02)
                    assert child_file.exists(), "child never started"
                    child_pid = int(child_file.read_text())
                    event.set()
                    with pytest.raises(asyncio.CancelledError):
                        await asyncio.wait_for(task, timeout=5)
                    for _ in range(50):
                        try:
                            state = Path(f"/proc/{child_pid}/stat").read_text().split(") ")[1][0]
                        except FileNotFoundError:
                            break
                        if state == "Z":
                            break
                        await asyncio.sleep(0.02)
                    else:
                        pytest.fail("child survived cancellation")
                finally:
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
    asyncio.run(scenario())
