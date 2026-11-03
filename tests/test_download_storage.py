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
