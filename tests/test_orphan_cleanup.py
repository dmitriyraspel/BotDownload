from bot.download_storage import create_task_directory
from bot.orphan_cleanup import remove_orphan_task_directory
from bot.storage import change_status, create_task, database, mark_file_ready


def test_explicit_cleanup_removes_single_orphan_file(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    folder = create_task_directory(root, "7")
    (folder / "partial.mp4").write_bytes(b"partial")
    db_path = tmp_path / "db.sqlite"
    assert remove_orphan_task_directory(db_path, str(root), folder)
    assert not folder.exists()


def test_explicit_cleanup_refuses_registered_file(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "db.sqlite"
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=1, chat_id=2, message_id=3,
            callback_key="registered", source_url="https://youtu.be/x",
            media_key="x", variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")
        assert change_status(db, task_id, "downloading", "processing")
        folder = create_task_directory(root, str(task_id))
        path = folder / "video.mp4"
        path.write_bytes(b"video")
        assert mark_file_ready(db, task_id, str(path))
    assert not remove_orphan_task_directory(db_path, str(root), folder)
    assert path.exists()


def test_explicit_cleanup_refuses_extra_contents(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    folder = create_task_directory(root, "3")
    (folder / "a.mp4").write_bytes(b"a")
    (folder / "b.mp4").write_bytes(b"b")
    assert not remove_orphan_task_directory(tmp_path / "db.sqlite", str(root), folder)
    assert len(list(folder.iterdir())) == 2


def test_explicit_cleanup_refuses_symlink(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    folder = create_task_directory(root, "3")
    target = tmp_path / "important"
    target.write_bytes(b"keep")
    (folder / "video.mp4").symlink_to(target)
    assert not remove_orphan_task_directory(tmp_path / "db.sqlite", str(root), folder)
    assert target.read_bytes() == b"keep"


def test_explicit_cleanup_refuses_outside_directory(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    assert not remove_orphan_task_directory(tmp_path / "db.sqlite", str(root), outside)
    assert outside.exists()
