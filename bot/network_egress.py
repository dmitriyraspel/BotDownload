"""Systemd transient-service confinement for an opt-in metadata worker.

Requires a privileged systemd manager and cgroup/BPF IP filtering. Merely
constructing this command does not prove that the host enforces the policy.
Do not enable until the deployment has passed live egress-denial checks.
"""
import os
from pathlib import Path


class EgressConfigurationError(RuntimeError):
    pass


# Explicitly deny private, loopback, link-local, shared, benchmark, multicast
# and reserved ranges. This is a minimum deny policy, not a public-IP allowlist.
DENIED_CIDRS = (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24",
    "192.0.2.0/24", "192.168.0.0/16", "198.18.0.0/15",
    "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4",
    "240.0.0.0/4", "::/128", "::1/128", "::ffff:0:0/96",
    "64:ff9b:1::/48", "100::/64", "2001:db8::/32",
    "fc00::/7", "fe80::/10", "ff00::/8",
)


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
