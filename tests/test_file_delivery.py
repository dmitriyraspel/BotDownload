import asyncio

import pytest

from bot.download_storage import create_task_directory
from bot.file_delivery import deliver_pending_file
from bot.storage import change_status, create_task, database, mark_file_ready


def setup_pending(tmp_path, *, content=b"ready"):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "db.sqlite"
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=9, chat_id=123, message_id=4,
            callback_key="delivery", source_url="https://youtu.be/x",
            media_key="x", variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")
        assert change_status(db, task_id, "downloading", "processing")
        folder = create_task_directory(root, str(task_id))
        path = folder / "video.mp4"
        if content is not None:
            path.write_bytes(content)
        assert mark_file_ready(db, task_id, str(path))
    return root, db_path, task_id, path


def test_delivery_marks_completed_only_after_sender_confirmation(tmp_path):
    root, db_path, task_id, path = setup_pending(tmp_path)
    calls = []

    async def sender(chat_id, file):
        calls.append((chat_id, file.read_bytes()))
        with database(db_path) as db:
            assert db.execute(
                "SELECT status FROM tasks WHERE id=?", (task_id,)
            ).fetchone()[0] == "uploading"
        return "telegram-file-id"

    assert asyncio.run(deliver_pending_file(
        db_path=db_path, task_id=task_id,
        configured_download_dir=str(root), sender=sender, max_bytes=100,
    ))
    assert calls == [(123, b"ready")]
    with database(db_path) as db:
        status, file_id = db.execute(
            "SELECT status,telegram_file_id FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
    assert (status, file_id) == ("completed", "telegram-file-id")
    assert path.exists()


def test_delivery_failure_quarantines_ambiguous_send_and_preserves_file(tmp_path):
    root, db_path, task_id, path = setup_pending(tmp_path)

    async def sender(chat_id, file):
        raise ConnectionError("Telegram unavailable")

    with pytest.raises(ConnectionError):
        asyncio.run(deliver_pending_file(
            db_path=db_path, task_id=task_id,
            configured_download_dir=str(root), sender=sender, max_bytes=100,
        ))
    with database(db_path) as db:
        assert db.execute(
            "SELECT status FROM tasks WHERE id=?", (task_id,)
        ).fetchone()[0] == "uploading"
    assert path.read_bytes() == b"ready"


def test_delivery_rejects_missing_file_without_sending(tmp_path):
    root, db_path, task_id, path = setup_pending(tmp_path, content=None)

    async def sender(chat_id, file):
        raise AssertionError("sender must not be called")

    assert not asyncio.run(deliver_pending_file(
        db_path=db_path, task_id=task_id,
        configured_download_dir=str(root), sender=sender, max_bytes=100,
    ))
    with database(db_path) as db:
        assert db.execute(
            "SELECT status FROM tasks WHERE id=?", (task_id,)
        ).fetchone()[0] == "failed"


def test_delivery_rejects_oversized_file(tmp_path):
    root, db_path, task_id, path = setup_pending(tmp_path, content=b"oversized")

    async def sender(chat_id, file):
        raise AssertionError("sender must not be called")

    assert not asyncio.run(deliver_pending_file(
        db_path=db_path, task_id=task_id,
        configured_download_dir=str(root), sender=sender, max_bytes=3,
    ))
    with database(db_path) as db:
        assert db.execute(
            "SELECT status FROM tasks WHERE id=?", (task_id,)
        ).fetchone()[0] == "failed"



def test_delivery_respects_daily_quota_before_sender(tmp_path):
    root, db_path, task_id, path = setup_pending(tmp_path)
    from bot.storage import create_task, record_delivery
    with database(db_path) as db:
        previous, _ = create_task(
            db, user_id=9, chat_id=123, message_id=99,
            callback_key="previous", source_url="https://youtu.be/x",
            media_key="x", variant="720p")
        for source, target in (("queued", "downloading"),
                               ("downloading", "processing"),
                               ("processing", "upload_pending"),
                               ("upload_pending", "uploading")):
            assert change_status(db, previous, source, target)
        from datetime import datetime, timezone
        assert record_delivery(db, previous, "prior-id",
                               datetime.now(timezone.utc).date().isoformat(),
                               cache_hit=False)

    async def sender(chat_id, file):
        raise AssertionError("quota exhausted; must not send")

    assert not asyncio.run(deliver_pending_file(
        db_path=db_path, task_id=task_id,
        configured_download_dir=str(root), sender=sender, max_bytes=100,
        daily_limit=1,
    ))
    with database(db_path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?",
                          (task_id,)).fetchone()[0] == "upload_pending"
