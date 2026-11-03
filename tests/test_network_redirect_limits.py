"""Offline checks for redirect-chain input limits and DNS safety."""
import socket

import pytest

from bot.network_security import UnsafeNetworkTarget, validate_redirect_chain


@pytest.mark.parametrize("limit", [None, True, False, -1, 1.5, "5", 21])
def test_redirect_chain_rejects_invalid_limit(limit):
    with pytest.raises(UnsafeNetworkTarget, match="перенаправлений"):
        validate_redirect_chain(["https://youtu.be/abc"], max_redirects=limit)


@pytest.mark.parametrize("urls", [None, "", "https://youtu.be/abc", [], {}, 42])
def test_redirect_chain_rejects_invalid_collection(urls):
    with pytest.raises(UnsafeNetworkTarget, match="перенаправлений"):
        validate_redirect_chain(urls)


def test_redirect_chain_rejects_excessive_hops_without_dns(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("DNS must not be queried")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    with pytest.raises(UnsafeNetworkTarget, match="перенаправлений"):
        validate_redirect_chain(["https://youtu.be/abc"] * 3, max_redirects=1)


def test_redirect_chain_accepts_zero_redirects_with_public_dns(monkeypatch):
    def public_dns(host, port, *, type):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    monkeypatch.setattr(socket, "getaddrinfo", public_dns)
    assert validate_redirect_chain(
        ["https://youtu.be/abc"], allowed_hosts={"youtu.be"}, max_redirects=0,
    ) == [("8.8.8.8",)]


def test_redirect_chain_rejects_private_second_hop(monkeypatch):
    def resolve(host, port, *, type):
        ip = "8.8.8.8" if host == "youtu.be" else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    with pytest.raises(UnsafeNetworkTarget, match="Локальный"):
        validate_redirect_chain(
            ["https://youtu.be/abc", "https://www.youtube.com/watch?v=abc"],
            allowed_hosts={"youtu.be", "www.youtube.com"},
        )
