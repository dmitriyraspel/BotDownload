import asyncio
import sys

import pytest

from bot.metadata_process import MetadataProcessError, run_json_subprocess


def test_json_process_returns_dict(tmp_path):
    result = asyncio.run(run_json_subprocess(
        [sys.executable, "-c", 'print(\'{"title":"ok"}\')'],
        cwd=tmp_path, timeout_seconds=3,
    ))
    assert result == {"title": "ok"}


def test_json_process_rejects_oversized_output(tmp_path):
    with pytest.raises(MetadataProcessError, match="большой"):
        asyncio.run(run_json_subprocess(
            [sys.executable, "-c", "print('x' * 100000)"],
            cwd=tmp_path, timeout_seconds=3, max_output_bytes=128,
        ))


def test_json_process_rejects_invalid_json(tmp_path):
    with pytest.raises(MetadataProcessError, match="Некорректный"):
        asyncio.run(run_json_subprocess(
            [sys.executable, "-c", "print('not-json')"],
            cwd=tmp_path, timeout_seconds=3,
        ))


def test_json_process_timeout(tmp_path):
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(run_json_subprocess(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            cwd=tmp_path, timeout_seconds=0.1,
        ))


@pytest.mark.parametrize("deadline", [0, -1, True, None, "5", float("nan"), float("inf")])
def test_json_process_rejects_invalid_deadline_before_spawn(tmp_path, deadline):
    with pytest.raises(MetadataProcessError, match="параметры"):
        asyncio.run(run_json_subprocess(
            [sys.executable, "-c", "print(1)"],
            cwd=tmp_path, timeout_seconds=deadline,
        ))


def test_json_process_rejects_missing_executable(tmp_path):
    with pytest.raises(MetadataProcessError, match="запустить"):
        asyncio.run(run_json_subprocess(
            [str(tmp_path / "nonexistent-executable")],
            cwd=tmp_path, timeout_seconds=2,
        ))


def test_json_process_rejects_nonobject_json(tmp_path):
    with pytest.raises(MetadataProcessError, match="объект"):
        asyncio.run(run_json_subprocess(
            [sys.executable, "-c", "print('[1, 2, 3]')"],
            cwd=tmp_path, timeout_seconds=3,
        ))


def test_json_process_rejects_nonzero_exit(tmp_path):
    with pytest.raises(MetadataProcessError, match="ошибкой"):
        asyncio.run(run_json_subprocess(
            [sys.executable, "-c", "import sys; print('{}'); sys.exit(2)"],
            cwd=tmp_path, timeout_seconds=3,
        ))
