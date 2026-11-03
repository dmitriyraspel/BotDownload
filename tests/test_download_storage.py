import os

import pytest

from bot.download_storage import (
    DownloadStorageError, cleanup_task_directory, create_task_directory, download_root,
)


def test_download_directory_lifecycle(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    unrelated = root / "keep.mp4"
    unrelated.write_bytes(b"keep")
    selected = download_root(str(root))
    task = create_task_directory(selected, "42")
    assert task.parent == selected
    assert task.stat().st_mode & 0o777 == 0o700
    (task / "media.mp4").write_bytes(b"temporary")
    cleanup_task_directory(selected, task)
    assert not task.exists()
    assert unrelated.read_bytes() == b"keep"


def test_reject_invalid_task_id(tmp_path):
    with pytest.raises(DownloadStorageError):
        create_task_directory(tmp_path, "../outside")


def test_reject_cleanup_outside_root(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    other = tmp_path / "task-123"
    other.mkdir()
    with pytest.raises(DownloadStorageError):
        cleanup_task_directory(root, other)
    assert other.exists()


def test_reject_download_root_symlink(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(DownloadStorageError):
        download_root(str(link))


def test_reject_cleanup_symlink(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    link = root / "task-1-link"
    link.symlink_to(external, target_is_directory=True)
    with pytest.raises(DownloadStorageError):
        cleanup_task_directory(root, link)
    assert external.exists()


def test_free_space_preflight(tmp_path, monkeypatch):
    from collections import namedtuple
    from bot.download_storage import require_free_space
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr("bot.download_storage.shutil.disk_usage",
                        lambda path: usage(1000, 600, 400))
    assert require_free_space(tmp_path, 300, reserve_bytes=100) == 400
    with pytest.raises(DownloadStorageError, match="свободного места"):
        require_free_space(tmp_path, 301, reserve_bytes=100)


@pytest.mark.parametrize("expected,reserve", [(0, 0), (-1, 0), (True, 0), (1, -1), (1, False)])
def test_free_space_rejects_invalid_limits(tmp_path, expected, reserve):
    from bot.download_storage import require_free_space
    with pytest.raises(DownloadStorageError):
        require_free_space(tmp_path, expected, reserve_bytes=reserve)


@pytest.mark.parametrize("name", [
    "task-42", "task-42-backup", "task-42-" + "g" * 32,
    "task-42-" + "a" * 31, "task-42-" + "a" * 33,
])
def test_cleanup_refuses_non_generated_directories(tmp_path, name):
    root = tmp_path / "downloads"
    root.mkdir()
    directory = root / name
    directory.mkdir(mode=0o700)
    marker = directory / "keep.txt"
    marker.write_text("keep")
    with pytest.raises(DownloadStorageError):
        cleanup_task_directory(root, directory)
    assert marker.read_text() == "keep"


def test_cleanup_refuses_publicly_accessible_task_directory(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    directory = create_task_directory(root, "42")
    marker = directory / "keep.txt"
    marker.write_text("keep")
    directory.chmod(0o755)
    with pytest.raises(DownloadStorageError):
        cleanup_task_directory(root, directory)
    assert marker.read_text() == "keep"


def test_cleanup_accepts_generated_alphanumeric_task_id(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    directory = create_task_directory(root, "abc_42")
    cleanup_task_directory(root, directory)
    assert not directory.exists()
