"""DNS preflight validation: deterministic offline resolver fixtures.

These checks are defense in depth, not a substitute for network confinement.
"""
import socket

import pytest

from bot.network_security import UnsafeNetworkTarget, validate_public_https_target


URL = "https://youtu.be/abc"
HOSTS = {"youtu.be"}


def lookup(monkeypatch, records):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: records)


@pytest.mark.parametrize("record", [
    (),
    ("invalid",),
    (socket.AF_UNIX, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 443)),
    (socket.AF_INET, socket.SOCK_DGRAM, 0, "", ("8.8.8.8", 443)),
    (socket.AF_INET, socket.SOCK_STREAM, 0, "", ()),
    (socket.AF_INET, socket.SOCK_STREAM, 0, "", "8.8.8.8"),
    (socket.AF_INET, socket.SOCK_STREAM, 0, "", (None, 443)),
    (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("2001:4860:4860::8888", 443)),
    (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 443)),
    (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("not-an-ip", 443)),
])
def test_rejects_malformed_dns_records(monkeypatch, record):
    lookup(monkeypatch, [record])
    with pytest.raises(UnsafeNetworkTarget):
        validate_public_https_target(URL, allowed_hosts=HOSTS)


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.0.0.1", "169.254.169.254",
    "192.168.0.1", "100.64.0.1", "192.0.2.1",
])
def test_rejects_nonpublic_ipv4_dns(monkeypatch, ip):
    lookup(monkeypatch, [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))])
    with pytest.raises(UnsafeNetworkTarget, match="Локальный"):
        validate_public_https_target(URL, allowed_hosts=HOSTS)


@pytest.mark.parametrize("ip", ["::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1"])
def test_rejects_nonpublic_ipv6_dns(monkeypatch, ip):
    lookup(monkeypatch, [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 443, 0, 0))])
    with pytest.raises(UnsafeNetworkTarget, match="Локальный"):
        validate_public_https_target(URL, allowed_hosts=HOSTS)


def test_rejects_mixed_public_and_private_dns(monkeypatch):
    lookup(monkeypatch, [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
    ])
    with pytest.raises(UnsafeNetworkTarget, match="Локальный"):
        validate_public_https_target(URL, allowed_hosts=HOSTS)


def test_accepts_public_ipv4_and_ipv6_dns(monkeypatch):
    lookup(monkeypatch, [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:4860:4860::8888", 443, 0, 0)),
    ])
    assert validate_public_https_target(URL, allowed_hosts=HOSTS) == (
        "2001:4860:4860::8888", "8.8.8.8",
    )


def test_rejects_empty_dns_response(monkeypatch):
    lookup(monkeypatch, [])
    with pytest.raises(UnsafeNetworkTarget, match="DNS"):
        validate_public_https_target(URL, allowed_hosts=HOSTS)
