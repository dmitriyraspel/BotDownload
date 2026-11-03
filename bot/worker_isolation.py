"""Fail-closed verification of the *offline* systemd worker unit.

This static check is not a substitute for kernel-level live egress tests.
It deliberately refuses to authorize network-capable downloads.
"""
from pathlib import Path


REQUIRED = {
    "NoNewPrivileges": "yes",
    "PrivateTmp": "yes",
    "PrivateDevices": "yes",
    "ProtectSystem": "strict",
    "ProtectHome": "yes",
    "RestrictAddressFamilies": "AF_UNIX",
    "IPAddressDeny": "any",
    "CapabilityBoundingSet": "",
    "RestrictSUIDSGID": "yes",
    "ProtectKernelTunables": "yes",
    "ProtectKernelModules": "yes",
    "ProtectControlGroups": "yes",
}


class IsolationConfigurationError(ValueError):
    pass


def verify_offline_unit(text: str) -> None:
    """Reject missing, conflicting or permissive worker settings."""
    if type(text) is not str:
        raise IsolationConfigurationError("Некорректный unit")
    section = None
    entries: dict[str, list[str]] = {}
    for original in text.splitlines():
        line = original.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section == "Service" and "=" in line:
            key, value = line.split("=", 1)
            entries.setdefault(key.strip(), []).append(value.strip())
    for key, value in REQUIRED.items():
        if entries.get(key) != [value]:
            raise IsolationConfigurationError(f"Не подтверждена изоляция: {key}")
    if entries.get("User") in (None, ["root"], ["0"]):
        raise IsolationConfigurationError("Worker не должен работать от root")
    if entries.get("ExecStart") is None or len(entries["ExecStart"]) != 1:
        raise IsolationConfigurationError("Неоднозначная команда запуска")
    if entries.get("IPAddressAllow") or entries.get("NetworkNamespacePath"):
        raise IsolationConfigurationError("Неожиданное сетевое исключение")


def verify_repository_offline_unit(path: Path) -> None:
    verify_offline_unit(path.read_text(encoding="utf-8"))
