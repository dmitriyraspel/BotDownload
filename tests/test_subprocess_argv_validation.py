"""Invalid process command containers must fail before subprocess spawning."""
from pathlib import Path

import pytest

from bot.metadata_process import MetadataProcessError, run_json_subprocess
from bot.process_runner import ProcessExecutionError, run_bounded_process


@pytest.mark.asyncio
@pytest.mark.parametrize("argv", [
    None, "", "python", b"python", 12, True, {},
    {"python"}, ("python", None), ["python", 123],
])
async def test_process_runner_rejects_invalid_argv(tmp_path, monkeypatch, argv):
    async def forbidden(*args, **kwargs):
        raise AssertionError("subprocess must not start")
    monkeypatch.setattr("bot.process_runner.asyncio.create_subprocess_exec", forbidden)
    with pytest.raises(ProcessExecutionError, match="команда"):
        await run_bounded_process(argv, cwd=tmp_path, timeout_seconds=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("argv", [
    None, "", "python", b"python", 12, True, {},
    {"python"}, ("python", None), ["python", 123],
])
async def test_metadata_runner_rejects_invalid_argv(tmp_path, monkeypatch, argv):
    async def forbidden(*args, **kwargs):
        raise AssertionError("subprocess must not start")
    monkeypatch.setattr("bot.metadata_process.asyncio.create_subprocess_exec", forbidden)
    with pytest.raises(MetadataProcessError, match="параметры"):
        await run_json_subprocess(argv, cwd=tmp_path, timeout_seconds=1)
