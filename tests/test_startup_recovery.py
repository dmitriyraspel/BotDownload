from bot.download_storage import create_task_directory
from bot.startup_recovery import recover_before_workers
from bot.storage import change_status, create_task, database, mark_file_ready


def task(db_path, key, state):
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=5, chat_id=1, message_id=1,
            callback_key=key, source_url="https://youtu.be/x",
            media_key="x", variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")
        if state in ("processing", "upload_pending", "uploading"):
            assert change_status(db, task_id, "downloading", "processing")
        return task_id


def test_startup_recovers_interrupted_and_valid_upload(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "db.sqlite"
    interrupted = task(db_path, "interrupted", "downloading")
    prepared = task(db_path, "prepared", "processing")
    folder = create_task_directory(root, str(prepared))
    path = folder / "video.mp4"
    path.write_bytes(b"ready")
    with database(db_path) as db:
        assert mark_file_ready(db, prepared, str(path))
        assert change_status(db, prepared, "upload_pending", "uploading")
    report = recover_before_workers(db_path, str(root))
    assert report.requeued == 1
    assert report.ready_files == 1
    assert report.missing_or_unsafe_files == 0
    assert report.orphan_directories == ()
    with database(db_path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?", (interrupted,)).fetchone()[0] == "queued"
        assert db.execute("SELECT status FROM tasks WHERE id=?", (prepared,)).fetchone()[0] == "upload_pending"
    assert path.read_bytes() == b"ready"


def test_startup_reports_orphans_and_marks_missing_files(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "db.sqlite"
    prepared = task(db_path, "missing", "processing")
    missing = create_task_directory(root, str(prepared)) / "missing.mp4"
    with database(db_path) as db:
        assert mark_file_ready(db, prepared, str(missing))
    orphan = create_task_directory(root, "999")
    (orphan / "partial.mp4").write_bytes(b"partial")
    report = recover_before_workers(db_path, str(root))
    assert report.ready_files == 0
    assert report.missing_or_unsafe_files == 1
    # A missing registered file is still registered and must not be auto-deleted.
    assert report.orphan_directories == (orphan,)
    with database(db_path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?", (prepared,)).fetchone()[0] == "failed"
    assert orphan.exists()


def test_startup_refuses_missing_storage_before_requeue(tmp_path):
    db_path = tmp_path / "db.sqlite"
    interrupted = task(db_path, "interrupted", "downloading")
    import pytest
    with pytest.raises(Exception):
        recover_before_workers(db_path, str(tmp_path / "missing"))
    with database(db_path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?", (interrupted,)).fetchone()[0] == "downloading"
