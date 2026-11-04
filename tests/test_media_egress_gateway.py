"""Offline admission tests for the outbound CONNECT gateway."""
import asyncio
import socket
from unittest.mock import patch

import pytest

from bot.media_egress_gateway import EgressDenied, parse_connect, permitted_host, public_ip, resolve_public


@pytest.mark.parametrize("host", [
    "youtube.com", "www.youtube.com", "r1---sn.googlevideo.com",
    "i.ytimg.com", "youtu.be",
])
def test_allowed_host(host):
    assert permitted_host(host)


@pytest.mark.parametrize("host", [
    "localhost", "127.0.0.1", "169.254.169.254", "youtube.com.evil.org",
    "evilgooglevideo.com", "youtube.com.", "YOUTUBE.COM", "a..youtube.com",
    "youtube.com:443", "xn--e1afmkfd.test",
])
def test_denied_host(host):
    assert not permitted_host(host)


def test_connect_only_tls_and_allowlisted_host():
    assert parse_connect(b"CONNECT www.youtube.com:443 HTTP/1.1") == ("www.youtube.com", 443)
    assert parse_connect(b"CONNECT www.youtube.com:443 HTTP/1.0") == ("www.youtube.com", 443)
    for request in (b"GET / HTTP/1.1", b"CONNECT youtube.com:80 HTTP/1.1",
                    b"CONNECT localhost:443 HTTP/1.1",
                    b"CONNECT youtube.com.evil.org:443 HTTP/1.1"):
        with pytest.raises(EgressDenied):
            parse_connect(request)


@pytest.mark.parametrize("ip", ["127.0.0.1", "127.0.0.254", "127.255.255.255", "::1"])
def test_v1_loopback_denied(ip):
    assert not public_ip(ip)


@pytest.mark.parametrize("address", [
    "8.8.8.8", "198.18.0.44", "198.18.0.6",
    "10.0.0.1", "192.168.1.2", "169.254.169.254",
    "fc00::1", "fe80::1", "0.0.0.0",
])
def test_v1_other_addresses_allowed(address):
    assert public_ip(address)


def test_mixed_dns_discards_only_loopback():
    async def scenario():
        loop = asyncio.get_running_loop()
        def fake(*args, **kwargs):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
            ]
        with patch.object(loop, "getaddrinfo", return_value=fake()):
            assert await resolve_public("youtube.com") == [(socket.AF_INET, "8.8.8.8")]
    asyncio.run(scenario())


def test_only_loopback_dns_is_denied():
    async def scenario():
        loop = asyncio.get_running_loop()
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        with patch.object(loop, "getaddrinfo", return_value=records):
            with pytest.raises(EgressDenied, match="only loopback addresses"):
                await resolve_public("youtube.com")
    asyncio.run(scenario())


def test_fake_ip_resolves_under_v1_policy():
    async def scenario():
        loop = asyncio.get_running_loop()
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.44", 443))]
        with patch.object(loop, "getaddrinfo", return_value=answers):
            assert await resolve_public("www.youtube.com") == [(socket.AF_INET, "198.18.0.44")]
    asyncio.run(scenario())
