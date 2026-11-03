import asyncio
import sys

import pytest

from bot.process_runner import ProcessExecutionError, run_bounded_process


def test_process_runner_success(tmp_path):
    result = asyncio.run(run_bounded_process(
        [sys.executable, "-c", "print('ok')"], cwd=tmp_path, timeout_seconds=5,
    ))
    assert result == 0


def test_process_runner_nonzero_exit(tmp_path):
    with pytest.raises(ProcessExecutionError, match="ошибкой"):
        asyncio.run(run_bounded_process(
            [sys.executable, "-c", "raise SystemExit(2)"],
            cwd=tmp_path, timeout_seconds=5,
        ))


def test_process_runner_timeout(tmp_path):
    with pytest.raises(ProcessExecutionError, match="время"):
        asyncio.run(run_bounded_process(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            cwd=tmp_path, timeout_seconds=0.1,
        ))


def test_process_runner_cancel(tmp_path):
    async def scenario():
        task = asyncio.create_task(run_bounded_process(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            cwd=tmp_path, timeout_seconds=30,
        ))
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())


@pytest.mark.parametrize("argv,timeout", [
    ([], 5), ([""], 5), (["echo", "bad\x00value"], 5),
    (["echo"], 0), (["echo"], -1), (["echo"], True),
])
def test_process_runner_rejects_invalid_arguments(tmp_path, argv, timeout):
    with pytest.raises(ProcessExecutionError):
        asyncio.run(run_bounded_process(argv, cwd=tmp_path, timeout_seconds=timeout))
