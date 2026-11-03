"""Runtime probe for the no-network Bubblewrap sandbox.

This is an offline readiness check, not a network-isolation proof. It must
succeed under the same service account and kernel restrictions as production.
"""
from pathlib import Path

from .network_isolation import SandboxUnavailable, isolated_no_network_command
from .process_runner import ProcessExecutionError, run_bounded_process


async def verify_no_network_sandbox(
    workspace: Path, *, bubblewrap: str | None = None,
    timeout_seconds: float = 5.0,
) -> None:
    """Execute a harmless binary inside the sandbox or fail closed.

    The probe verifies that Bubblewrap can start and exit successfully.
    It does not demonstrate that a downloader is SSRF-safe.
    """
    if timeout_seconds <= 0:
        raise SandboxUnavailable("Недопустимый тайм-аут проверки песочницы")
    command = isolated_no_network_command(
        ["/usr/bin/true"], workspace=workspace, bubblewrap=bubblewrap,
    )
    try:
        await run_bounded_process(
            command, cwd=workspace, timeout_seconds=timeout_seconds,
        )
    except (ProcessExecutionError, OSError) as exc:
        raise SandboxUnavailable(
            "Песочница не запустилась: проверьте bubblewrap, права и настройки ядра"
        ) from exc
