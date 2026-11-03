import pytest

from bot.download_storage import DownloadStorageError
from bot.task_workspace import task_workspace


def test_workspace_cleans_after_success(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    keep = root / "keep.txt"
    keep.write_text("keep")
    with task_workspace(str(root), "job-1", 100, reserve_bytes=0) as work:
        assert work.parent == root
        (work / "video.mp4").write_bytes(b"content")
        assert work.exists()
    assert not work.exists()
    assert keep.read_text() == "keep"


def test_workspace_cleans_after_failure(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    with pytest.raises(ValueError, match="processing failed"):
        with task_workspace(str(root), "job-2", 100, reserve_bytes=0) as work:
            (work / "partial.mp4").write_bytes(b"partial")
            raise ValueError("processing failed")
    assert list(root.iterdir()) == []


def test_workspace_does_not_create_on_insufficient_space(tmp_path, monkeypatch):
    root = tmp_path / "downloads"
    root.mkdir()
    monkeypatch.setattr("bot.download_storage.shutil.disk_usage",
                        lambda path: type("Usage", (), {"free": 100})())
    with pytest.raises(DownloadStorageError, match="свободного места"):
        with task_workspace(str(root), "job-3", 101, reserve_bytes=0):
            pytest.fail("workspace must not be created")
    assert list(root.iterdir()) == []


def test_workspace_does_not_create_when_root_missing(tmp_path):
    root = tmp_path / "missing"
    with pytest.raises(DownloadStorageError):
        with task_workspace(str(root), "job-4", 100, reserve_bytes=0):
            pytest.fail("workspace must not be created")
    assert not root.exists()
