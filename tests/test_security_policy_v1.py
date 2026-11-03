"""Regression tests for the user-approved security policy v1."""
import ast
from pathlib import Path

from bot.network_egress import DENIED_CIDRS
from bot.telegram_handlers import validate_media_url
from bot.downloader import build_command


def test_only_loopback_is_denied_by_v1():
    assert DENIED_CIDRS == ("127.0.0.0/8", "::1/128")
    assert "198.18.0.0/15" not in DENIED_CIDRS


def test_user_can_only_supply_approved_https_host():
    assert validate_media_url("https://www.youtube.com/watch?v=abc")
    assert validate_media_url("https://www.tiktok.com/@example/video/123")
    for url in (
        "https://127.0.0.1/",
        "https://youtube.com.attacker.example/watch?v=abc",
        "http://www.youtube.com/watch?v=abc",
        "https://www.youtube.com:8080/watch?v=abc",
        "https://user:pass@www.youtube.com/watch?v=abc",
    ):
        assert not validate_media_url(url)


def test_download_command_is_service_owned(tmp_path):
    cmd = build_command("https://www.youtube.com/watch?v=abc", "480p", 100000, tmp_path)
    assert cmd[-2:] == ["--", "https://www.youtube.com/watch?v=abc"]
    assert "--ignore-config" in cmd
    assert "--no-plugin-dirs" in cmd
    assert "--no-playlist" in cmd
    assert "--format" in cmd
    assert "height=480" in cmd[cmd.index("--format") + 1]


def test_metadata_has_no_fake_ip_rejecting_dns_preflight():
    root = Path(__file__).resolve().parents[1]
    for name in ("metadata_process.py", "metadata_worker.py"):
        tree = ast.parse((root / "bot" / name).read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        assert not any(
            isinstance(c.func, ast.Name) and c.func.id == "validate_public_https_target"
            for c in calls
        )
