"""Offline tests for the opt-in systemd egress policy."""
import ipaddress
from pathlib import Path

import pytest

from bot import network_egress


@pytest.mark.parametrize("address", [
    "127.0.0.1", "127.255.255.254", "::1",
])
def test_v1_egress_policy_covers_loopback(address):
    target = ipaddress.ip_address(address)
    assert any(target in ipaddress.ip_network(cidr)
               for cidr in network_egress.DENIED_CIDRS)


def test_v1_does_not_block_fake_ip_or_lan():
    for address in ("198.18.0.44", "10.1.2.3", "192.168.1.1", "169.254.169.254"):
        target = ipaddress.ip_address(address)
        assert not any(target in ipaddress.ip_network(cidr) for cidr in network_egress.DENIED_CIDRS)


def test_egress_guard_requires_root(monkeypatch):
    monkeypatch.setattr(network_egress.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(Path, "is_dir", lambda self: True)
    with pytest.raises(network_egress.EgressConfigurationError, match="привилегий"):
        network_egress.systemd_metadata_guard(["python", "-m", "bot.metadata_worker"])


def test_egress_guard_builds_constrained_service(monkeypatch):
    monkeypatch.setattr(network_egress.os, "geteuid", lambda: 0)
    monkeypatch.setattr(Path, "is_dir", lambda self: True)
    cmd = network_egress.systemd_metadata_guard(["python", "-m", "bot.metadata_worker"])
    assert cmd[0] == "systemd-run"
    assert "--property=User=tgbot" in cmd
    assert f"--property=WorkingDirectory={Path(network_egress.__file__).resolve().parent.parent}" in cmd
    assert "--property=NoNewPrivileges=yes" in cmd
    assert any(arg.startswith("--property=IPAddressDeny=") for arg in cmd)
    assert cmd[-3:] == ["python", "-m", "bot.metadata_worker"]


def test_egress_guard_rejects_invalid_command(monkeypatch):
    monkeypatch.setattr(network_egress.os, "geteuid", lambda: 0)
    monkeypatch.setattr(Path, "is_dir", lambda self: True)
    with pytest.raises(network_egress.EgressConfigurationError):
        network_egress.systemd_metadata_guard(["python", "bad\x00argument"])


@pytest.mark.parametrize("user", [
    None, True, 1, "", "1bot", "-bot", "bad user",
    "bad;user", "юзер", "a" * 33,
])
def test_egress_guard_rejects_invalid_service_accounts(monkeypatch, user):
    monkeypatch.setattr(network_egress.os, "geteuid", lambda: 0)
    monkeypatch.setattr(Path, "is_dir", lambda self: True)
    with pytest.raises(network_egress.EgressConfigurationError, match="пользователя"):
        network_egress.systemd_metadata_guard(["python"], user=user)


@pytest.mark.parametrize("command", [None, "", "python", [], [True], [42], [""]])
def test_egress_guard_rejects_invalid_command_shapes(monkeypatch, command):
    monkeypatch.setattr(network_egress.os, "geteuid", lambda: 0)
    monkeypatch.setattr(Path, "is_dir", lambda self: True)
    with pytest.raises(network_egress.EgressConfigurationError, match="команда"):
        network_egress.systemd_metadata_guard(command)


def test_egress_guard_accepts_portable_service_account(monkeypatch):
    monkeypatch.setattr(network_egress.os, "geteuid", lambda: 0)
    monkeypatch.setattr(Path, "is_dir", lambda self: True)
    cmd = network_egress.systemd_metadata_guard(["python"], user="media_worker-1")
    assert "--property=User=media_worker-1" in cmd


@pytest.mark.parametrize("property_name", [
    "PrivateDevices=yes",
    "ProtectKernelTunables=yes",
    "ProtectKernelModules=yes",
    "ProtectControlGroups=yes",
    "RestrictSUIDSGID=yes",
    "LockPersonality=yes",
    "CapabilityBoundingSet=",
    "UMask=0077",
    "MemoryMax=1G",
    "TasksMax=32",
    "RuntimeMaxSec=120",
    "LimitFSIZE=2147483648",
])
def test_egress_guard_has_resource_and_privilege_limits(monkeypatch, property_name):
    monkeypatch.setattr(network_egress.os, "geteuid", lambda: 0)
    monkeypatch.setattr(Path, "is_dir", lambda self: True)
    cmd = network_egress.systemd_metadata_guard(["python"])
    assert "--property=" + property_name in cmd


def test_egress_guard_passes_command_only_after_separator(monkeypatch):
    monkeypatch.setattr(network_egress.os, "geteuid", lambda: 0)
    monkeypatch.setattr(Path, "is_dir", lambda self: True)
    payload = ["python", "--property=MemoryMax=infinity"]
    cmd = network_egress.systemd_metadata_guard(payload)
    assert cmd[cmd.index("--") + 1:] == payload
    assert cmd.index("--property=MemoryMax=1G") < cmd.index("--")
