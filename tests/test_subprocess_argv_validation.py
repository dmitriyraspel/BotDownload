"""Invalid process command containers must fail before subprocess spawning."""
import asyncio

import pytest

from bot.metadata_process import MetadataProcessError, run_json_subprocess
from bot.process_runner import ProcessExecutionError, run_bounded_process


@pytest.mark.parametrize("argv", [
    None, "", "python", b"python", 12, True, {},
    {"python"}, ("python", None), ["python", 123],
])
def test_process_runner_rejects_invalid_argv(tmp_path, monkeypatch, argv):
    async def forbidden(*args, **kwargs):
        raise AssertionError("subprocess must not start")
    monkeypatch.setattr("bot.process_runner.asyncio.create_subprocess_exec", forbidden)
    with pytest.raises(ProcessExecutionError, match="команда"):
        asyncio.run(run_bounded_process(argv, cwd=tmp_path, timeout_seconds=1))


@pytest.mark.parametrize("argv", [
    None, "", "python", b"python", 12, True, {},
    {"python"}, ("python", None), ["python", 123],
])
def test_metadata_runner_rejects_invalid_argv(tmp_path, monkeypatch, argv):
    async def forbidden(*args, **kwargs):
        raise AssertionError("subprocess must not start")
    monkeypatch.setattr("bot.metadata_process.asyncio.create_subprocess_exec", forbidden)
    with pytest.raises(MetadataProcessError, match="параметры"):
        asyncio.run(run_json_subprocess(argv, cwd=tmp_path, timeout_seconds=1))
