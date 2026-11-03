from bot.download_storage import create_task_directory
from bot.ready_cleanup import cleanup_terminal_files
from bot.storage import change_status, create_task, database, mark_file_ready


def make_terminal(tmp_path, status):
    root = tmp_path / "downloads"
    root.mkdir(exist_ok=True)
    db_path = tmp_path / "db.sqlite"
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=5, chat_id=1, message_id=1,
            callback_key=status, source_url="https://youtu.be/x",
            media_key="x", variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")
        assert change_status(db, task_id, "downloading", "processing")
        folder = create_task_directory(root, str(task_id))
        path = folder / "video.mp4"
        path.write_bytes(b"video")
        assert mark_file_ready(db, task_id, str(path))
        if status == "cancelled":
            assert change_status(db, task_id, "upload_pending", "cancelled")
        elif status == "failed":
            assert change_status(db, task_id, "upload_pending", "failed")
        elif status == "completed":
            assert change_status(db, task_id, "upload_pending", "uploading")
            assert change_status(db, task_id, "uploading", "completed")
    return db_path, root, task_id, path


def test_cleanup_completed_file(tmp_path):
    db_path, root, task_id, path = make_terminal(tmp_path, "completed")
    assert cleanup_terminal_files(db_path, str(root)) == (1, 0)
    assert not path.exists()
    assert not path.parent.exists()
    with database(db_path) as db:
        assert db.execute("SELECT ready_file FROM tasks WHERE id=?", (task_id,)).fetchone()[0] is None
    assert cleanup_terminal_files(db_path, str(root)) == (0, 0)


def test_cleanup_cancelled_file(tmp_path):
    db_path, root, _, path = make_terminal(tmp_path, "cancelled")
    assert cleanup_terminal_files(db_path, str(root)) == (1, 0)
    assert not path.exists()


def test_cleanup_failed_file(tmp_path):
    db_path, root, _, path = make_terminal(tmp_path, "failed")
    assert cleanup_terminal_files(db_path, str(root)) == (1, 0)
    assert not path.exists()


def test_cleanup_refuses_extra_file(tmp_path):
    db_path, root, task_id, path = make_terminal(tmp_path, "completed")
    extra = path.parent / "unexpected.txt"
    extra.write_text("keep")
    assert cleanup_terminal_files(db_path, str(root)) == (0, 1)
    assert path.exists() and extra.exists()
    with database(db_path) as db:
        assert db.execute("SELECT ready_file FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == str(path)


def test_cleanup_does_not_touch_pending_file(tmp_path):
    db_path, root, task_id, path = make_terminal(tmp_path, "completed")
    with database(db_path) as db:
        db.execute("UPDATE tasks SET status='upload_pending' WHERE id=?", (task_id,))
    assert cleanup_terminal_files(db_path, str(root)) == (0, 0)
    assert path.exists()
