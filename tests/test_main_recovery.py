"""Entrypoint must recover durable tasks before starting Telegram polling."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from bot import main as entrypoint
from bot.startup_recovery import RecoveryReport


def test_main_recovers_before_polling(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    events = []
    settings = SimpleNamespace(data={
        "logging": {
            "level": "INFO", "max_file_size_mb": 1, "backup_count": 1,
        },
        "storage": {"download_dir": str(tmp_path)},
        "telegram": {"api_mode": "cloud"},
    })
    monkeypatch.setattr(entrypoint, "load_settings", lambda: settings)
    monkeypatch.setattr(entrypoint.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(entrypoint, "initialize", lambda path: events.append("initialize"))
    monkeypatch.setattr(
        entrypoint, "recover_before_workers",
        lambda path, root: events.append("recover")
        or RecoveryReport(0, 0, 0, ()),
    )

    async def fake_polling(settings):
        events.append("polling")

    monkeypatch.setattr(entrypoint, "run_bot", fake_polling)
    entrypoint.main()
    assert events == ["initialize", "recover", "polling"]


def test_main_does_not_poll_if_recovery_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    settings = SimpleNamespace(data={
        "logging": {"level": "INFO", "max_file_size_mb": 1, "backup_count": 1},
        "storage": {"download_dir": str(tmp_path)},
        "telegram": {"api_mode": "cloud"},
    })
    monkeypatch.setattr(entrypoint, "load_settings", lambda: settings)
    monkeypatch.setattr(entrypoint.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(entrypoint, "initialize", lambda path: None)

    def failed(*args):
        raise RuntimeError("recovery failed")

    monkeypatch.setattr(entrypoint, "recover_before_workers", failed)

    async def must_not_poll(settings):
        raise AssertionError("polling started")

    monkeypatch.setattr(entrypoint, "run_bot", must_not_poll)
    import pytest
    with pytest.raises(SystemExit):
        entrypoint.main()
