from bot.download_storage import create_task_directory
from bot.orphan_inventory import find_orphan_task_directories
from bot.storage import change_status, create_task, database, mark_file_ready


def test_inventory_finds_unregistered_private_directory(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    folder = create_task_directory(root, "7")
    (folder / "partial.mp4").write_bytes(b"partial")
    db_path = tmp_path / "db.sqlite"
    assert find_orphan_task_directories(db_path, str(root)) == [folder]
    assert (folder / "partial.mp4").read_bytes() == b"partial"


def test_inventory_excludes_registered_directory(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "db.sqlite"
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=1, chat_id=2, message_id=3,
            callback_key="orphan-test", source_url="https://youtu.be/x",
            media_key="x", variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")
        assert change_status(db, task_id, "downloading", "processing")
        folder = create_task_directory(root, str(task_id))
        path = folder / "video.mp4"
        path.write_bytes(b"ready")
        assert mark_file_ready(db, task_id, str(path))
    assert find_orphan_task_directories(db_path, str(root)) == []
    assert path.exists()


def test_inventory_ignores_foreign_and_symlink_directories(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    (root / "personal").mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (root / ("task-1-" + "a" * 32)).symlink_to(external, target_is_directory=True)
    db_path = tmp_path / "db.sqlite"
    assert find_orphan_task_directories(db_path, str(root)) == []
    assert external.exists()


def test_inventory_rejects_nonprivate_directory(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    folder = create_task_directory(root, "4")
    folder.chmod(0o755)
    db_path = tmp_path / "db.sqlite"
    assert find_orphan_task_directories(db_path, str(root)) == []
    assert folder.exists()
