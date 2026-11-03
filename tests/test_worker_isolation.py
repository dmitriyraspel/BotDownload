"""Offline worker isolation unit tests."""
from pathlib import Path

import pytest

from bot.worker_isolation import IsolationConfigurationError, verify_offline_unit


UNIT = Path(__file__).resolve().parents[1] / "deploy" / "botdownload-worker.service.example"


def test_offline_unit_has_required_isolation():
    verify_offline_unit(UNIT.read_text(encoding="utf-8"))


@pytest.mark.parametrize("replacement", [
    "IPAddressDeny=localhost",
    "RestrictAddressFamilies=AF_UNIX AF_INET",
    "NoNewPrivileges=no",
    "ProtectSystem=full",
    "PrivateDevices=no",
])
def test_relaxed_unit_fails_closed(replacement):
    original = UNIT.read_text(encoding="utf-8")
    key = replacement.split("=", 1)[0]
    old = next(line for line in original.splitlines() if line.startswith(key + "="))
    with pytest.raises(IsolationConfigurationError):
        verify_offline_unit(original.replace(old, replacement))


def test_duplicate_setting_is_rejected():
    with pytest.raises(IsolationConfigurationError):
        verify_offline_unit(UNIT.read_text(encoding="utf-8").replace("IPAddressDeny=any", "IPAddressDeny=any\nIPAddressDeny=any"))


def test_network_allow_is_rejected():
    with pytest.raises(IsolationConfigurationError):
        verify_offline_unit(UNIT.read_text(encoding="utf-8") + "\n[Service]\nIPAddressAllow=0.0.0.0/0\n")


@pytest.mark.parametrize("replacement", [
    "User=root",
    "User=root",
    "Group=root",
    "RuntimeDirectoryMode=0777",
    "UMask=0000",
    "Environment=BOTDOWNLOAD_CLIENT_USER=root",
])
def test_worker_rejects_unsafe_service_settings(replacement):
    original = UNIT.read_text(encoding="utf-8")
    key = replacement.split("=", 1)[0]
    old = next(line for line in original.splitlines() if line.startswith(key + "="))
    with pytest.raises(IsolationConfigurationError):
        verify_offline_unit(original.replace(old, replacement))
