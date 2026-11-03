"""Tests for the controlled loopback egress diagnostic."""
import socket

from bot import egress_loopback_probe


def test_child_can_connect_to_controlled_listener(capsys):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        assert egress_loopback_probe._connect(server.getsockname()[1]) == 0
        conn, _ = server.accept()
        conn.close()
    assert capsys.readouterr().out.strip() == "CONNECTED"


def test_child_reports_failed_connection(capsys, monkeypatch):
    def reject(*args, **kwargs):
        raise ConnectionRefusedError("refused")
    monkeypatch.setattr(socket, "create_connection", reject)
    assert egress_loopback_probe._connect(12345) == 1
    assert capsys.readouterr().out.strip().startswith("BLOCKED_OR_FAILED:")


def test_baseline_failure_never_passes(monkeypatch, capsys):
    class Result:
        returncode = 1
        stdout = "BLOCKED_OR_FAILED:TimeoutError\n"
        stderr = ""
    monkeypatch.setattr(egress_loopback_probe.subprocess, "run",
                        lambda *args, **kwargs: Result())
    assert egress_loopback_probe.main([]) == 2
    assert "INCONCLUSIVE" in capsys.readouterr().out


def test_ipv6_child_uses_ipv6_loopback(monkeypatch, capsys):
    destinations = []
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
    def connect(destination, timeout):
        destinations.append((destination, timeout))
        return Connection()
    monkeypatch.setattr(socket, "create_connection", connect)
    assert egress_loopback_probe._connect(12345, ipv6=True) == 0
    assert destinations == [(("::1", 12345), 2)]
    assert capsys.readouterr().out.strip() == "CONNECTED"
