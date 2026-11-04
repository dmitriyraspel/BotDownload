"""Stage 2 real-media IPC and publication tests; no external network."""
from pathlib import Path

from bot.worker_ipc import parse_request
from bot.storage import database, create_task, change_status
from bot.media_ipc_client import publish_media_file
from bot.download_storage import create_task_directory


def test_execute_media_protocol():
    request = parse_request(
        b'{"version":1,"op":"execute_media","task_id":1,"token":"' +
        b"a" * 64 + b'"}'
    )
    assert request["op"] == "execute_media"


def test_media_result_is_published_atomically(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "tasks.sqlite"
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=1, chat_id=1, message_id=1,
            callback_key="publish-media", source_url="https://youtu.be/abcdefghijk",
            media_key="test", variant="video",
        )
        assert change_status(db, task_id, "queued", "downloading")
    directory = create_task_directory(root, str(task_id))
    file = directory / "video.mp4"
    file.write_bytes(b"offline-test-bytes")
    assert publish_media_file(
        db_path=db_path, task_id=task_id, result=file,
        configured_download_dir=str(root),
    )
    with database(db_path) as db:
        row = db.execute(
            "SELECT status,ready_file FROM tasks WHERE id=?", (task_id,),
        ).fetchone()
    assert row[0] == "upload_pending"
    assert Path(row[1]).read_bytes() == b"offline-test-bytes"
    assert not directory.exists()
