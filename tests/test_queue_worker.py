from bot.queue_worker import inspect_next_queued, queued_task_cancelled
from bot.storage import cancel_task, create_task, database


def test_inspect_queue_does_not_claim_task(tmp_path):
    path = tmp_path / "bot.sqlite"
    with database(path) as db:
        first, _ = create_task(
            db, user_id=11, chat_id=1, message_id=1,
            callback_key="a", source_url="https://youtu.be/a",
            media_key="a", variant="720p",
        )
        second, _ = create_task(
            db, user_id=11, chat_id=1, message_id=2,
            callback_key="b", source_url="https://youtu.be/b",
            media_key="b", variant="MP3",
        )
    assert inspect_next_queued(path) == first
    assert inspect_next_queued(path) == first
    with database(path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?", (first,)).fetchone()[0] == "queued"
        assert db.execute("SELECT status FROM tasks WHERE id=?", (second,)).fetchone()[0] == "queued"


def test_inspect_queue_skips_cancelled(tmp_path):
    path = tmp_path / "bot.sqlite"
    with database(path) as db:
        first, _ = create_task(
            db, user_id=11, chat_id=1, message_id=1,
            callback_key="a", source_url="https://youtu.be/a",
            media_key="a", variant="720p",
        )
        assert cancel_task(db, task_id=first, user_id=11)
    assert queued_task_cancelled(path, first)
    assert inspect_next_queued(path) is None
    assert not queued_task_cancelled(path, 999)
