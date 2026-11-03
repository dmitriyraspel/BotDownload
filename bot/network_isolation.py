"""Fail-closed Linux network namespace wrapper for untrusted subprocesses.

A no-network namespace is useful for offline FFmpeg/media inspection, but
cannot by itself run yt-dlp: the downloader will require a separately
controlled network transport. This module never silently falls back to an
unisolated command.
"""
import os
from pathlib import Path
import shutil


class SandboxUnavailable(RuntimeError):
    """Required OS isolation could not be established."""


def isolated_no_network_command(
    argv: list[str], *, workspace: Path,
    bubblewrap: str | None = None,
) -> list[str]:
    """Construct bubblewrap argv with an empty network namespace.

    This is a command builder, not a proof of kernel sandbox availability.
    A caller must execute it with a bounded process runner and fail on
    bwrap startup errors. No shell or network fallback is permitted.
    """
    if os.name != "posix" or not Path("/proc/self/ns/net").exists():
        raise SandboxUnavailable("Требуется Linux с network namespaces")
    if not argv or any(type(arg) is not str or not arg or "\x00" in arg for arg in argv):
        raise SandboxUnavailable("Недопустимая команда")
    if not workspace.is_absolute() or workspace.is_symlink() or not workspace.is_dir():
        raise SandboxUnavailable("Требуется существующий абсолютный рабочий каталог")
    executable = bubblewrap or shutil.which("bwrap")
    if not executable or not Path(executable).is_absolute() or not Path(executable).is_file():
        raise SandboxUnavailable("Bubblewrap недоступен")
    return [
        executable,
        "--die-with-parent",
        "--new-session",
        "--unshare-net",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--proc", "/proc",
        "--dev", "/dev",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind-try", "/bin", "/bin",
        "--ro-bind-try", "/lib", "/lib",
        "--ro-bind-try", "/lib64", "/lib64",
        "--tmpfs", "/tmp",
        "--bind", str(workspace), "/work",
        "--chdir", "/work",
        "--",
        *argv,
    ]
