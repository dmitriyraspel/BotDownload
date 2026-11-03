"""SSRF preflight regression tests; socket pinning is still required."""
import socket

import pytest

from bot.network_security import UnsafeNetworkTarget, validate_public_https_target


def test_preflight_accepts_public_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
    ])
    assert validate_public_https_target(
        "https://www.youtube.com/watch?v=1", allowed_hosts={"www.youtube.com"},
    ) == ("8.8.8.8",)


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.1", "169.254.169.254", "::1",
    "::ffff:127.0.0.1", "fc00::1",
])
def test_preflight_rejects_private_and_mapped_addresses(monkeypatch, address):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, 443)),
    ])
    with pytest.raises(UnsafeNetworkTarget):
        validate_public_https_target("https://www.youtube.com/watch?v=1")


@pytest.mark.parametrize("url", [
    "https://www.youtube.com./watch",
    "https://-youtube.com/watch",
    "https://www.youtube.com@127.0.0.1/watch",
    "https://www.youtube.com:444/watch",
    "https://127.0.0.1/watch",
    "http://www.youtube.com/watch",
])
def test_preflight_rejects_ambiguous_or_forbidden_url(monkeypatch, url):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
    ])
    with pytest.raises(UnsafeNetworkTarget):
        validate_public_https_target(url)
