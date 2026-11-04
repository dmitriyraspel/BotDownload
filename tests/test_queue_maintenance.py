"""Offline queue maintenance never processes queued media as fake downloads."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from bot.queue_maintenance import maintain_queue, run_queue_maintenance
from bot.storage import create_task, database


def test_expire_old_job_but_preserve_new_job(tmp_path):
    db_path = tmp_path / "tasks.sqlite"
    with database(db_path) as db:
        old, _ = create_task(db, user_id=1, chat_id=1, message_id=1,
                             callback_key="old", source_url="https://youtu.be/x",
                             media_key="x", variant="MP3")
        fresh, _ = create_task(db, user_id=1, chat_id=1, message_id=2,
                               callback_key="fresh", source_url="https://youtu.be/y",
                               media_key="y", variant="MP3")
        timestamp = (datetime.now(timezone.utc) - timedelta(minutes=40)).strftime("%Y-%m-%dT%H:%M:%fZ")
        db.execute("UPDATE tasks SET created_at=? WHERE id=?", (timestamp, old))
    assert maintain_queue(db_path) == (1, 0)
    with database(db_path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?", (old,)).fetchone()[0] == "failed"
        assert db.execute("SELECT status FROM tasks WHERE id=?", (fresh,)).fetchone()[0] == "queued"
    assert maintain_queue(db_path) == (0, 0)


def test_maintenance_stops_without_claiming_jobs(tmp_path):
    db_path = tmp_path / "tasks.sqlite"
    with database(db_path) as db:
        task, _ = create_task(db, user_id=1, chat_id=1, message_id=1,
                              callback_key="new", source_url="https://youtu.be/x",
                              media_key="x", variant="MP3")

    async def scenario():
        stop = asyncio.Event()
        runner = asyncio.create_task(run_queue_maintenance(
            stop=stop, db_path=db_path, idle_seconds=0.01,
        ))
        await asyncio.sleep(0.03)
        stop.set()
        await asyncio.wait_for(runner, timeout=1)

    asyncio.run(scenario())
    with database(db_path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?", (task,)).fetchone()[0] == "queued"


def test_invalid_wait_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        maintain_queue(tmp_path / "tasks.sqlite", max_wait_minutes=0)
