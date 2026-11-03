"""Tests for DNS and TCP egress diagnostic."""
import socket

from bot import egress_dns_probe


def test_dns_failure_is_reported(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise socket.gaierror("resolver unavailable")
    monkeypatch.setattr(socket, "getaddrinfo", fail)
    assert egress_dns_probe.diagnose() == 2
    assert "DNS_FAIL:" in capsys.readouterr().out


def test_public_tcp_success(monkeypatch, capsys):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))])
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
    monkeypatch.setattr(socket, "create_connection",
                        lambda *args, **kwargs: Connection())
    assert egress_dns_probe.diagnose() == 0
    output = capsys.readouterr().out
    assert "DNS_OK:" in output
    assert "TCP_OK:" in output


def test_tcp_failure_is_reported(monkeypatch, capsys):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))])
    def fail(*args, **kwargs):
        raise TimeoutError("timeout")
    monkeypatch.setattr(socket, "create_connection", fail)
    assert egress_dns_probe.diagnose() == 2
    assert "TCP_FAIL:" in capsys.readouterr().out
