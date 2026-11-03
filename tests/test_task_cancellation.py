from pathlib import Path

from bot.storage import (
    cancel_task,
    create_task,
    database,
    task_is_cancelled,
)


def test_cancel_only_own_task(tmp_path):
    with database(tmp_path / "bot.sqlite") as db:
        task_id, created = create_task(
            db, user_id=101, chat_id=5, message_id=6,
            callback_key="cancel-own", source_url="https://youtu.be/abc",
            media_key="media", variant="720p",
        )
        assert created
        assert not cancel_task(db, task_id=task_id, user_id=202)
        assert not task_is_cancelled(db, task_id)
        assert cancel_task(db, task_id=task_id, user_id=101)
        assert task_is_cancelled(db, task_id)
        assert not cancel_task(db, task_id=task_id, user_id=101)


def test_cancel_unknown_task(tmp_path):
    with database(tmp_path / "bot.sqlite") as db:
        assert not cancel_task(db, task_id=999, user_id=101)
        assert not task_is_cancelled(db, 999)
        assert not cancel_task(db, task_id=-1, user_id=101)


def test_cancel_task_persists(tmp_path):
    path = tmp_path / "bot.sqlite"
    with database(path) as db:
        task_id, _ = create_task(
            db, user_id=101, chat_id=5, message_id=7,
            callback_key="cancel-persist", source_url="https://youtu.be/def",
            media_key="media2", variant="MP3",
        )
        assert cancel_task(db, task_id=task_id, user_id=101)
    with database(path) as db:
        assert task_is_cancelled(db, task_id)
