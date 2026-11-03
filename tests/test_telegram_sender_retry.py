import asyncio
from types import SimpleNamespace

from bot.storage import create_task, change_status, database
from bot.telegram_sender import send_staged_file
from bot.upload_retry import reserve_upload_attempt, schedule_upload_retry


def pending(db_path):
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=1, chat_id=2, message_id=3,
            callback_key="retry", source_url="https://youtu.be/x",
            media_key="x", variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")
        assert change_status(db, task_id, "downloading", "processing")
        assert change_status(db, task_id, "processing", "upload_pending")
    return task_id


def test_upload_attempts_and_retry_limit(tmp_path):
    db_path = tmp_path / "db.sqlite"
    task_id = pending(db_path)
    assert reserve_upload_attempt(db_path, task_id, max_attempts=2)
    assert schedule_upload_retry(db_path, task_id, max_attempts=2, delay_seconds=0)
    assert reserve_upload_attempt(db_path, task_id, max_attempts=2)
    assert not schedule_upload_retry(db_path, task_id, max_attempts=2, delay_seconds=0)
    with database(db_path) as db:
        assert db.execute(
            "SELECT status,upload_attempts FROM tasks WHERE id=?", (task_id,)
        ).fetchone() == ("failed", 2)


def test_retry_waits_until_due(tmp_path):
    db_path = tmp_path / "db.sqlite"
    task_id = pending(db_path)
    assert reserve_upload_attempt(db_path, task_id, max_attempts=3)
    assert schedule_upload_retry(db_path, task_id, max_attempts=3, delay_seconds=3600)
    assert not reserve_upload_attempt(db_path, task_id, max_attempts=3)
    with database(db_path) as db:
        assert db.execute(
            "SELECT upload_attempts FROM tasks WHERE id=?", (task_id,)
        ).fetchone()[0] == 1


def test_telegram_adapter_sends_mp4(tmp_path):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"video")

    class FakeBot:
        async def send_video(self, *, chat_id, video, supports_streaming):
            assert chat_id == 123
            assert supports_streaming
            assert video.path == path
            return SimpleNamespace(video=SimpleNamespace(file_id="video-id"))

    assert asyncio.run(send_staged_file(FakeBot(), 123, path)) == "video-id"


def test_telegram_adapter_sends_mp3(tmp_path):
    path = tmp_path / "audio.mp3"
    path.write_bytes(b"audio")

    class FakeBot:
        async def send_audio(self, *, chat_id, audio):
            assert chat_id == 123
            assert audio.path == path
            return SimpleNamespace(audio=SimpleNamespace(file_id="audio-id"))

    assert asyncio.run(send_staged_file(FakeBot(), 123, path)) == "audio-id"
