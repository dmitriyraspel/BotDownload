import asyncio
from types import SimpleNamespace

from bot.download_storage import create_task_directory
from bot.storage import change_status, create_task, database, mark_file_ready
from bot.upload_coordinator import upload_one_task


def pending(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "db.sqlite"
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=3, chat_id=456, message_id=7,
            callback_key="upload", source_url="https://youtu.be/x",
            media_key="x", variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")
        assert change_status(db, task_id, "downloading", "processing")
        folder = create_task_directory(root, str(task_id))
        path = folder / "video.mp4"
        path.write_bytes(b"video")
        assert mark_file_ready(db, task_id, str(path))
    return root, db_path, task_id, path


def call(bot, root, db_path, task_id, *, max_attempts=2, second_delay=0):
    return asyncio.run(upload_one_task(
        bot=bot, db_path=db_path, task_id=task_id,
        configured_download_dir=str(root), max_bytes=100,
        max_attempts=max_attempts,
        second_attempt_delay_seconds=second_delay,
        third_attempt_delay_seconds=0,
    ))


def test_coordinator_completes_successful_send(tmp_path):
    root, db_path, task_id, path = pending(tmp_path)

    class Bot:
        async def send_video(self, *, chat_id, video, supports_streaming):
            assert chat_id == 456
            return SimpleNamespace(video=SimpleNamespace(file_id="tg-id"))

    assert call(Bot(), root, db_path, task_id)
    with database(db_path) as db:
        assert db.execute(
            "SELECT status,upload_attempts,telegram_file_id FROM tasks WHERE id=?",
            (task_id,),
        ).fetchone() == ("completed", 1, "tg-id")
    assert path.exists()


def test_coordinator_quarantines_ambiguous_send_without_retry(tmp_path):
    root, db_path, task_id, path = pending(tmp_path)
    calls = []

    class Bot:
        async def send_video(self, *, chat_id, video, supports_streaming):
            calls.append(chat_id)
            raise ConnectionError("unavailable")

    bot = Bot()
    assert not call(bot, root, db_path, task_id)
    assert not call(bot, root, db_path, task_id)
    assert calls == [456]
    with database(db_path) as db:
        assert db.execute(
            "SELECT status,upload_attempts FROM tasks WHERE id=?", (task_id,)
        ).fetchone() == ("uploading", 1)
        assert db.execute(
            "SELECT COUNT(*) FROM delivery_reservations WHERE task_id=?",
            (task_id,)
        ).fetchone()[0] == 1
    assert path.read_bytes() == b"video"


def test_coordinator_refuses_invalid_file_without_telegram_call(tmp_path):
    root, db_path, task_id, path = pending(tmp_path)
    path.unlink()

    class Bot:
        async def send_video(self, **kwargs):
            raise AssertionError("should not send")

    assert not call(Bot(), root, db_path, task_id)
    with database(db_path) as db:
        assert db.execute(
            "SELECT status FROM tasks WHERE id=?", (task_id,),
        ).fetchone()[0] == "failed"
