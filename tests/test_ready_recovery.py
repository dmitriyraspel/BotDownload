from bot.download_storage import create_task_directory
from bot.ready_recovery import inspect_pending_files, valid_ready_file
from bot.storage import change_status, create_task, database, mark_file_ready


def pending(db_path, key):
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=9, chat_id=1, message_id=1,
            callback_key=key, source_url="https://youtu.be/x",
            media_key="x", variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")
        assert change_status(db, task_id, "downloading", "processing")
    return task_id


def publish(db_path, task_id, path):
    with database(db_path) as db:
        assert mark_file_ready(db, task_id, str(path))


def status(db_path, task_id):
    with database(db_path) as db:
        return db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0]


def test_recovery_preserves_valid_ready_file(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "db.sqlite"
    task_id = pending(db_path, "valid")
    folder = create_task_directory(root, str(task_id))
    path = folder / "video.mp4"
    path.write_bytes(b"video")
    publish(db_path, task_id, path)
    assert inspect_pending_files(db_path, str(root)) == (1, 0)
    assert status(db_path, task_id) == "upload_pending"
    assert path.read_bytes() == b"video"


def test_recovery_marks_missing_file_failed(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "db.sqlite"
    task_id = pending(db_path, "missing")
    folder = create_task_directory(root, str(task_id))
    publish(db_path, task_id, folder / "missing.mp4")
    assert inspect_pending_files(db_path, str(root)) == (0, 1)
    assert status(db_path, task_id) == "failed"
    assert folder.is_dir()


def test_recovery_rejects_foreign_path_without_deleting(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    foreign = root / "foreign.mp4"
    foreign.write_bytes(b"untouched")
    db_path = tmp_path / "db.sqlite"
    task_id = pending(db_path, "foreign")
    publish(db_path, task_id, foreign)
    assert not valid_ready_file(root.resolve(), task_id, str(foreign))
    assert inspect_pending_files(db_path, str(root)) == (0, 1)
    assert foreign.read_bytes() == b"untouched"


def test_recovery_rejects_symlink(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "db.sqlite"
    task_id = pending(db_path, "symlink")
    folder = create_task_directory(root, str(task_id))
    target = root / "unrelated.mp4"
    target.write_bytes(b"keep")
    link = folder / "video.mp4"
    link.symlink_to(target)
    publish(db_path, task_id, link)
    assert inspect_pending_files(db_path, str(root)) == (0, 1)
    assert target.read_bytes() == b"keep"


def test_recovery_rejects_publicly_accessible_staging_directory(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "db.sqlite"
    task_id = pending(db_path, "unsafe-permissions")
    folder = create_task_directory(root, str(task_id))
    path = folder / "video.mp4"
    path.write_bytes(b"video")
    publish(db_path, task_id, path)
    folder.chmod(0o755)
    assert not valid_ready_file(root.resolve(), task_id, str(path))
    assert inspect_pending_files(db_path, str(root)) == (0, 1)
    assert status(db_path, task_id) == "failed"
    assert path.read_bytes() == b"video"
