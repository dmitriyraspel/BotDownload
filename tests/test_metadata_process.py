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
