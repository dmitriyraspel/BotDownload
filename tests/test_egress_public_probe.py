"""Tests for the opt-in public HTTPS sandbox diagnostic."""
from bot import egress_public_probe


def test_public_probe_reports_success(monkeypatch, capsys):
    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def read(self, size):
            return b"x"
    monkeypatch.setattr(egress_public_probe.urllib.request, "urlopen",
                        lambda *args, **kwargs: Response())
    assert egress_public_probe.fetch_public_https() == 0
    assert capsys.readouterr().out.strip() == "HTTPS_OK"


def test_public_probe_fails_closed_on_network_error(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise OSError("network unavailable")
    monkeypatch.setattr(egress_public_probe.urllib.request, "urlopen", fail)
    assert egress_public_probe.fetch_public_https() == 2
    assert "UNREACHABLE" in capsys.readouterr().out


def test_public_probe_fails_closed_on_http_error(monkeypatch, capsys):
    class Response:
        status = 403
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def read(self, size):
            return b"x"
    monkeypatch.setattr(egress_public_probe.urllib.request, "urlopen",
                        lambda *args, **kwargs: Response())
    assert egress_public_probe.fetch_public_https() == 2
    assert capsys.readouterr().out.strip() == "HTTP_STATUS:403"
