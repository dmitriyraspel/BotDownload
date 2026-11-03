"""Offline checks for the live egress diagnostic."""
import errno
import socket

from bot import egress_probe


def test_probe_reports_permission_denied(monkeypatch, capsys):
    class BlockedSocket:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def settimeout(self, seconds):
            pass
        def connect(self, destination):
            raise PermissionError(errno.EPERM, "blocked")
    monkeypatch.setattr(socket, "socket", lambda *args: BlockedSocket())
    assert egress_probe.probe_target("127.0.0.1", 443) == 0
    assert capsys.readouterr().out.strip() == "DENIED"


def test_probe_does_not_treat_refused_as_blocked(monkeypatch, capsys):
    class RefusedSocket:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def settimeout(self, seconds):
            pass
        def connect(self, destination):
            raise ConnectionRefusedError(errno.ECONNREFUSED, "refused")
    monkeypatch.setattr(socket, "socket", lambda *args: RefusedSocket())
    assert egress_probe.probe_target("127.0.0.1", 443) == 2
    assert "INCONCLUSIVE" in capsys.readouterr().out


def test_probe_connected_is_unsafe(monkeypatch, capsys):
    class ConnectedSocket:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def settimeout(self, seconds):
            pass
        def connect(self, destination):
            pass
    monkeypatch.setattr(socket, "socket", lambda *args: ConnectedSocket())
    assert egress_probe.probe_target("127.0.0.1", 443) == 1
    assert capsys.readouterr().out.strip() == "CONNECTED"


def test_probe_cli_rejects_invalid_port():
    import pytest
    with pytest.raises(SystemExit):
        egress_probe.main(["--port", "0"])
