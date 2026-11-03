import pytest

from bot.download_storage import (
    DownloadStorageError, cleanup_task_directory, create_task_directory,
)
from bot.ready_files import stage_ready_file


def test_stage_ready_file_survives_workspace_cleanup(tmp_path):
    workspace = create_task_directory(tmp_path, "7")
    (workspace / "movie.mp4").write_bytes(b"video")
    ready = stage_ready_file(tmp_path, workspace, "movie.mp4", "7")
    assert ready.read_bytes() == b"video"
    assert ready.parent != workspace
    assert not (workspace / "movie.mp4").exists()
    cleanup_task_directory(tmp_path, workspace)
    assert ready.read_bytes() == b"video"
    cleanup_task_directory(tmp_path, ready.parent)
    assert not list(tmp_path.iterdir())


def test_stage_ready_file_rejects_symlink(tmp_path):
    workspace = create_task_directory(tmp_path, "8")
    (workspace / "outside.mp4").symlink_to(tmp_path / "outside.mp4")
    with pytest.raises(DownloadStorageError):
        stage_ready_file(tmp_path, workspace, "outside.mp4", "8")
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("filename", ["../escape", "/tmp/escape", ".", "..", ""])
def test_stage_ready_file_rejects_unsafe_filename(tmp_path, filename):
    workspace = create_task_directory(tmp_path, "9")
    with pytest.raises(DownloadStorageError):
        stage_ready_file(tmp_path, workspace, filename, "9")
    assert len(list(tmp_path.iterdir())) == 1


def test_stage_ready_file_rejects_non_workspace(tmp_path):
    workspace = tmp_path / "arbitrary"
    workspace.mkdir()
    (workspace / "video.mp4").write_bytes(b"video")
    with pytest.raises(DownloadStorageError):
        stage_ready_file(tmp_path, workspace, "video.mp4", "10")


def test_stage_rejects_workspace_belonging_to_another_task(tmp_path):
    workspace = create_task_directory(tmp_path, "11")
    (workspace / "video.mp4").write_bytes(b"video")
    with pytest.raises(DownloadStorageError):
        stage_ready_file(tmp_path, workspace, "video.mp4", "12")
    assert (workspace / "video.mp4").read_bytes() == b"video"


def test_stage_rejects_world_accessible_workspace(tmp_path):
    workspace = create_task_directory(tmp_path, "13")
    (workspace / "video.mp4").write_bytes(b"video")
    workspace.chmod(0o755)
    with pytest.raises(DownloadStorageError):
        stage_ready_file(tmp_path, workspace, "video.mp4", "13")


@pytest.mark.parametrize("filename", [".hidden.mp4", "empty.mp4"])
def test_stage_rejects_hidden_and_empty_files(tmp_path, filename):
    workspace = create_task_directory(tmp_path, "14")
    (workspace / filename).touch()
    with pytest.raises(DownloadStorageError):
        stage_ready_file(tmp_path, workspace, filename, "14")
    assert (workspace / filename).exists()


def test_stage_rejects_hardlinked_file(tmp_path):
    import os
    workspace = create_task_directory(tmp_path, "15")
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"video")
    os.link(outside, workspace / "video.mp4")
    with pytest.raises(DownloadStorageError):
        stage_ready_file(tmp_path, workspace, "video.mp4", "15")
    assert outside.read_bytes() == b"video"
