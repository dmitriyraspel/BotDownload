"""Safe media executor admission and disabled-by-default boundary."""
import asyncio

import pytest

from bot.media_executor import UnsafeMediaRequest, execute_media_download, validate_media_url


@pytest.mark.parametrize("url", [
    "http://youtube.com/watch?v=x",
    "https://youtube.com.evil.test/watch?v=x",
    "https://127.0.0.1/watch?v=x",
    "https://localhost/watch?v=x",
    "https://user:pass@youtube.com/watch?v=x",
    "https://youtube.com:8443/watch?v=x",
    "file:///etc/passwd",
    "https://youtube.com/watch?v=x\n--exec",
    "https://youtube.com/watch?v=x#fragment",
    "https://[::1]/",
    "https://youtube.com./watch?v=x",
])
def test_rejects_unsafe_url(url):
    with pytest.raises(UnsafeMediaRequest):
        validate_media_url(url)


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=abc",
    "https://youtu.be/abc",
    "https://m.youtube.com/shorts/abc",
])
def test_admits_only_expected_https_hosts(url):
    assert validate_media_url(url) == url


def test_executor_disabled_before_any_file_or_network_access(tmp_path):
    async def scenario():
        with pytest.raises(UnsafeMediaRequest, match="отключены"):
            await execute_media_download(
                "https://youtu.be/abc",
                configured_download_dir=str(tmp_path / "nonexistent"),
            )
    asyncio.run(scenario())


def test_executor_rejects_bad_limits_without_spawning(tmp_path):
    async def scenario():
        with pytest.raises(UnsafeMediaRequest, match="ограничения"):
            await execute_media_download(
                "https://youtu.be/abc", enabled=True,
                configured_download_dir=str(tmp_path),
                max_bytes=0,
            )
    asyncio.run(scenario())


def test_pre_cancelled_executor_does_not_create_workspace(tmp_path):
    async def scenario():
        stop = asyncio.Event()
        stop.set()
        with pytest.raises(asyncio.CancelledError):
            await execute_media_download(
                "https://youtu.be/abc", enabled=True,
                configured_download_dir=str(tmp_path), cancel=stop,
            )
        assert list(tmp_path.iterdir()) == []
    asyncio.run(scenario())
