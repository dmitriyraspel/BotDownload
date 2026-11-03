from pathlib import Path

import pytest

from bot import network_isolation


def test_no_network_sandbox_builds_explicit_namespace(tmp_path, monkeypatch):
    executable = tmp_path / "bwrap"
    executable.write_bytes(b"fake")
    monkeypatch.setattr(network_isolation.os, "name", "posix")
    original_exists = Path.exists
    monkeypatch.setattr(
        network_isolation.Path, "exists",
        lambda self: True if str(self) == "/proc/self/ns/net" else original_exists(self),
    )
    cmd = network_isolation.isolated_no_network_command(
        ["/usr/bin/ffmpeg", "-version"],
        workspace=tmp_path, bubblewrap=str(executable),
    )
    assert "--unshare-net" in cmd
    assert "--die-with-parent" in cmd
    assert cmd[-3:] == ["--", "/usr/bin/ffmpeg", "-version"]
    assert "--bind" in cmd
    assert cmd[cmd.index("--bind") + 1] == str(tmp_path)


def test_no_network_sandbox_rejects_missing_bubblewrap(tmp_path, monkeypatch):
    monkeypatch.setattr(network_isolation.shutil, "which", lambda name: None)
    with pytest.raises(network_isolation.SandboxUnavailable):
        network_isolation.isolated_no_network_command(
            ["/usr/bin/ffmpeg"], workspace=tmp_path,
        )


def test_no_network_sandbox_rejects_relative_workspace(tmp_path):
    with pytest.raises(network_isolation.SandboxUnavailable):
        network_isolation.isolated_no_network_command(
            ["/usr/bin/ffmpeg"], workspace=Path("relative"),
        )


def test_no_network_sandbox_rejects_invalid_argv(tmp_path):
    with pytest.raises(network_isolation.SandboxUnavailable):
        network_isolation.isolated_no_network_command(
            ["ffmpeg", "bad\x00arg"], workspace=tmp_path,
        )
