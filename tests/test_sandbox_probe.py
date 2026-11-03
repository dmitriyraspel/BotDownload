import asyncio

import pytest

from bot import sandbox_probe
from bot.network_isolation import SandboxUnavailable
from bot.process_runner import ProcessExecutionError


def test_probe_runs_isolated_command(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setattr(
        sandbox_probe, "isolated_no_network_command",
        lambda argv, *, workspace, bubblewrap: ["bwrap", "--unshare-net", "--", *argv],
    )

    async def fake_runner(argv, *, cwd, timeout_seconds):
        calls.append((argv, cwd, timeout_seconds))

    monkeypatch.setattr(sandbox_probe, "run_bounded_process", fake_runner)
    asyncio.run(sandbox_probe.verify_no_network_sandbox(tmp_path, timeout_seconds=2))
    assert calls == [(
        ["bwrap", "--unshare-net", "--", "/usr/bin/true"], tmp_path, 2,
    )]


def test_probe_fails_closed_on_bubblewrap_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sandbox_probe, "isolated_no_network_command",
        lambda argv, *, workspace, bubblewrap: ["bwrap"],
    )

    async def fake_runner(argv, *, cwd, timeout_seconds):
        raise ProcessExecutionError("unshare not permitted")

    monkeypatch.setattr(sandbox_probe, "run_bounded_process", fake_runner)
    with pytest.raises(SandboxUnavailable, match="не запустилась"):
        asyncio.run(sandbox_probe.verify_no_network_sandbox(tmp_path))


def test_probe_does_not_run_with_invalid_timeout(monkeypatch, tmp_path):
    async def forbidden(*args, **kwargs):
        raise AssertionError("runner must not be called")

    monkeypatch.setattr(sandbox_probe, "run_bounded_process", forbidden)
    with pytest.raises(SandboxUnavailable, match="тайм-аут"):
        asyncio.run(sandbox_probe.verify_no_network_sandbox(
            tmp_path, timeout_seconds=0,
        ))
