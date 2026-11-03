"""Allowed-host policy validation must fail before DNS."""
import socket

import pytest

from bot.network_security import UnsafeNetworkTarget, validate_public_https_target


@pytest.mark.parametrize("hosts", [
    [], {}, (), "", "youtu.be", {"YOUTU.BE"}, {None},
    {42}, {"youtu.be", None}, frozenset(),
])
def test_rejects_invalid_allowed_host_policy_without_dns(monkeypatch, hosts):
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected DNS")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    with pytest.raises(UnsafeNetworkTarget, match="разрешённых доменов"):
        validate_public_https_target("https://youtu.be/abc", allowed_hosts=hosts)


def test_accepts_frozen_allowlist(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        ],
    )
    assert validate_public_https_target(
        "https://youtu.be/abc", allowed_hosts=frozenset({"youtu.be"}),
    ) == ("8.8.8.8",)


def test_rejects_unlisted_domain_without_dns(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected DNS")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    with pytest.raises(UnsafeNetworkTarget, match="Домен"):
        validate_public_https_target(
            "https://youtu.be/abc", allowed_hosts={"www.youtube.com"},
        )
