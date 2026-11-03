from bot.storage import (
    cancel_task, change_status, create_task, database,
    get_pending_file, mark_file_ready,
)


def _processing(db):
    task_id, _ = create_task(
        db, user_id=42, chat_id=1, message_id=1,
        callback_key="ready-test", source_url="https://youtu.be/a",
        media_key="a", variant="720p",
    )
    assert change_status(db, task_id, "queued", "downloading")
    assert change_status(db, task_id, "downloading", "processing")
    return task_id


def test_ready_file_persists_across_connections(tmp_path):
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        task_id = _processing(db)
        assert mark_file_ready(db, task_id, "/safe/private/video.mp4")
        assert not mark_file_ready(db, task_id, "/other/video.mp4")
    with database(path) as db:
        assert get_pending_file(db, task_id) == "/safe/private/video.mp4"
        assert db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "upload_pending"


def test_cancelled_task_cannot_publish_file(tmp_path):
    with database(tmp_path / "db.sqlite") as db:
        task_id = _processing(db)
        assert cancel_task(db, task_id=task_id, user_id=42)
        assert not mark_file_ready(db, task_id, "/safe/private/video.mp4")
        assert get_pending_file(db, task_id) is None


def test_ready_file_rejects_invalid_state_and_path(tmp_path):
    with database(tmp_path / "db.sqlite") as db:
        task_id = _processing(db)
        assert not mark_file_ready(db, 0, "/safe/file")
        assert not mark_file_ready(db, 999, "/safe/file")
        for bad in ("", " ", "bad\\x00path"):
            try:
                mark_file_ready(db, task_id, bad)
            except ValueError:
                pass
            else:
                raise AssertionError("Invalid path accepted")
        assert get_pending_file(db, task_id) is None
