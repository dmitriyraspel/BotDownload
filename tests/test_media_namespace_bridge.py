"""Security regression tests for media namespace bridge and launcher.

No external network access or yt-dlp execution.
"""
import asyncio
import socket
from unittest.mock import patch

import pytest

from bot.media_namespace_bridge import serve_bridge
from bot.media_namespace_entry import entry_command
from bot.media_executor import UnsafeMediaRequest


def test_namespace_command_is_explicit_and_no_shell(tmp_path):
    gateway = tmp_path / "egress.sock"
    with socket.socket(socket.AF_UNIX) as sock:
        sock.bind(str(gateway))
        with patch("bot.media_namespace_entry.shutil.which", return_value="/usr/bin/unshare"):
            cmd = entry_command(
                "https://www.youtube.com/watch?v=abcdefghijk",
                gateway, timeout_seconds=30, max_bytes=1024,
            )
    assert cmd[:5] == ["/usr/bin/unshare", "--user", "--map-root-user", "--net", "--fork"]
    assert "shell" not in cmd
    assert "bot.media_namespace_entry" in cmd


def test_bridge_forwards_bytes_to_unix_gateway(tmp_path):
    async def scenario():
        path = tmp_path / "egress.sock"
        async def gateway(reader, writer):
            data = await reader.read(128)
            writer.write(data[::-1])
            await writer.drain()
            writer.close()
        upstream = await asyncio.start_unix_server(gateway, path=str(path))
        bridge, port = await serve_bridge(path)
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"test")
            await writer.drain()
            assert await asyncio.wait_for(reader.read(4), 2) == b"tset"
            writer.close()
            await writer.wait_closed()
        finally:
            bridge.close()
            upstream.close()
            await bridge.wait_closed()
            await upstream.wait_closed()
    asyncio.run(scenario())


def test_bridge_fails_closed_without_gateway(tmp_path):
    async def scenario():
        with pytest.raises(ValueError):
            await serve_bridge(tmp_path / "missing.sock")
    asyncio.run(scenario())
