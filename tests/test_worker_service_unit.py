"""Static regression checks for the opt-in dedicated worker unit."""
from pathlib import Path


UNIT = Path(__file__).resolve().parents[1] / "deploy" / "botdownload-worker.service.example"


def test_worker_unit_runs_as_separate_unprivileged_account():
    text = UNIT.read_text(encoding="utf-8")
    assert "User=botdownload-worker" in text
    assert "Group=tgbot" in text
    assert "NoNewPrivileges=yes" in text
    assert "CapabilityBoundingSet=" in text


def test_worker_unit_has_no_ip_network_access():
    text = UNIT.read_text(encoding="utf-8")
    assert "RestrictAddressFamilies=AF_UNIX" in text
    assert "IPAddressDeny=any" in text


def test_worker_unit_has_bounded_resources_and_private_runtime():
    text = UNIT.read_text(encoding="utf-8")
    assert "MemoryMax=256M" in text
    assert "TasksMax=16" in text
    assert "RuntimeDirectory=botdownload-worker" in text
    assert "RuntimeDirectoryMode=0750" in text
    assert "ProtectSystem=strict" in text
