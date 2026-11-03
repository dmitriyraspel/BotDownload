"""Reject unsafe URLs before attempting any DNS lookup."""
import socket

import pytest

from bot.network_security import UnsafeNetworkTarget, validate_public_https_target


@pytest.mark.parametrize("url", [
    "http://youtu.be/abc",
    "https://127.0.0.1/abc",
    "https://user:pass@youtu.be/abc",
    "https://youtu.be:444/abc",
    "https://youtu.be/abc#fragment",
    "https://youtu.be\\@127.0.0.1/abc",
    "https://youtu.be%2eexample.org/abc",
    "https://-bad.example/abc",
    "https://bad-.example/abc",
    "https://youtu.be/abc\n",
    "https://youtu.be/" + "x" * 2050,
    "https://other.example/abc",
])
def test_invalid_target_never_queries_dns(monkeypatch, url):
    def forbidden(*args, **kwargs):
        raise AssertionError("DNS called for rejected URL")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    with pytest.raises(UnsafeNetworkTarget):
        validate_public_https_target(url, allowed_hosts={"youtu.be"})


def test_resolver_failure_is_controlled_error(monkeypatch):
    def failure(*args, **kwargs):
        raise socket.gaierror("resolver unavailable")
    monkeypatch.setattr(socket, "getaddrinfo", failure)
    with pytest.raises(UnsafeNetworkTarget, match="безопасно"):
        validate_public_https_target(
            "https://youtu.be/abc", allowed_hosts={"youtu.be"},
        )
