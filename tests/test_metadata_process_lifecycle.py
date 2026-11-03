"""Process cancellation and output contract regression tests."""
import asyncio
import sys

import pytest

from bot.metadata_process import MetadataProcessError, run_json_subprocess


def test_json_process_rejects_non_object(tmp_path):
    with pytest.raises(MetadataProcessError, match="объект"):
        asyncio.run(run_json_subprocess(
            [sys.executable, "-c", "print('[1, 2, 3]')"],
            cwd=tmp_path, timeout_seconds=3,
        ))


def test_json_process_rejects_nonzero_exit(tmp_path):
    with pytest.raises(MetadataProcessError, match="ошибкой"):
        asyncio.run(run_json_subprocess(
            [sys.executable, "-c", "import sys; sys.exit(7)"],
            cwd=tmp_path, timeout_seconds=3,
        ))


def test_json_process_rejects_invalid_limits(tmp_path):
    with pytest.raises(MetadataProcessError, match="параметры"):
        asyncio.run(run_json_subprocess(
            [sys.executable, "-c", "print('{}')"],
            cwd=tmp_path, timeout_seconds=3, max_output_bytes=0,
        ))


def test_json_process_cancellation(tmp_path):
    async def scenario():
        task = asyncio.create_task(run_json_subprocess(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=tmp_path, timeout_seconds=40,
        ))
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3)

    asyncio.run(scenario())
