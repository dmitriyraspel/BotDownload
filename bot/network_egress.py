"""Systemd transient-service confinement for an opt-in metadata worker.

Requires a privileged systemd manager and cgroup/BPF IP filtering. Merely
constructing this command does not prove that the host enforces the policy.
Do not enable until the deployment has passed live egress-denial checks.
"""
import os
from pathlib import Path


class EgressConfigurationError(RuntimeError):
    pass


# Approved v1 policy: deny loopback only. Never block Fake-IP 198.18/15.
# Applying these rules requires systemd/cgroup BPF support and a live test.
DENIED_CIDRS = ("127.0.0.0/8", "::1/128")


def systemd_metadata_guard(command: list[str], *, user: str = "tgbot") -> list[str]:
    """Build a transient service command; only a privileged operator can run it.

    IPAddressDeny is enforced by systemd's cgroup BPF hooks when supported.
    A live test of blocked connections is mandatory before production use.
    """
    if os.name != "posix" or not Path("/run/systemd/system").is_dir():
        raise EgressConfigurationError("Для изоляции требуется systemd")
    if os.geteuid() != 0:
        raise EgressConfigurationError("Запуск изолированного сервиса требует привилегий")
    if (not isinstance(user, str) or not 1 <= len(user) <= 32
            or not user.isascii() or not user[0].isalpha()
            or not all(ch.isascii() and (ch.isalnum() or ch in "_-") for ch in user)):
        raise EgressConfigurationError("Недопустимое имя пользователя")
    if (not isinstance(command, (list, tuple)) or not command
            or any(type(arg) is not str or not arg or "\x00" in arg for arg in command)):
        raise EgressConfigurationError("Недопустимая команда")
    project_root = Path(__file__).resolve().parent.parent
    return [
        "systemd-run", "--system", "--quiet", "--wait", "--pipe", "--collect",
        "--property=Type=exec", f"--property=User={user}",
        f"--property=WorkingDirectory={project_root}",
        "--property=NoNewPrivileges=yes", "--property=PrivateTmp=yes",
        "--property=PrivateDevices=yes", "--property=ProtectKernelTunables=yes",
        "--property=ProtectKernelModules=yes", "--property=ProtectControlGroups=yes",
        "--property=RestrictSUIDSGID=yes", "--property=LockPersonality=yes",
        "--property=CapabilityBoundingSet=", "--property=UMask=0077",
        "--property=ProtectSystem=strict", "--property=ProtectHome=yes",
        "--property=MemoryMax=1G", "--property=TasksMax=32",
        "--property=RuntimeMaxSec=120", "--property=LimitFSIZE=2147483648",
        "--property=RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        "--property=IPAddressDeny=" + " ".join(DENIED_CIDRS),
        "--", *command,
    ]
