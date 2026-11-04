"""Offline gateway socket tests; no network requests."""
import asyncio

from bot.media_egress_gateway import handle_connect


def test_gateway_rejects_mismatched_host_and_non_connect(tmp_path):
    async def scenario():
        path = tmp_path / "gateway.sock"
        server = await asyncio.start_unix_server(handle_connect, path=str(path))
        try:
            for request in (
                b"CONNECT youtube.com:443 HTTP/1.1\r\nHost: localhost:443\r\n\r\n",
                b"CONNECT youtube.com:443 HTTP/1.1\r\nHost: youtube.com:443\r\nHost: youtube.com:443\r\n\r\n",
                b"CONNECT youtube.com:443 HTTP/1.1\r\n\r\n",
                b"CONNECT localhost:443 HTTP/1.1\r\nHost: localhost:443\r\n\r\n",
                b"GET / HTTP/1.1\r\nHost: youtube.com:443\r\n\r\n",
            ):
                reader, writer = await asyncio.open_unix_connection(str(path))
                writer.write(request)
                await writer.drain()
                response = await asyncio.wait_for(reader.read(256), timeout=2)
                assert response.startswith(b"HTTP/1.1 403 Forbidden")
                writer.close()
                await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()
    asyncio.run(scenario())
