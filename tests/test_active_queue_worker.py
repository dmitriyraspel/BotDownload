import asyncio

from bot.queue_worker import process_next_queued_task, run_queue_worker
from bot.storage import create_task, database


def enqueue(db_path, key):
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=7, chat_id=1, message_id=1,
            callback_key=key, source_url="https://youtu.be/x",
            media_key="x", variant="720p",
        )
    return task_id


def test_queue_worker_prepares_one_file(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "db.sqlite"
    task_id = enqueue(db_path, "first")

    async def processor(workspace, task_id):
        (workspace / "ready.mp4").write_bytes(b"ready")
        return "ready.mp4"

    result = asyncio.run(process_next_queued_task(
        db_path=db_path, configured_download_dir=str(root),
        expected_bytes=1, processor=processor, max_wait_minutes=30,
        reserve_bytes=0,
    ))
    assert result == task_id
    with database(db_path) as db:
        row = db.execute(
            "SELECT status,ready_file FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
    assert row[0] == "upload_pending"
    assert __import__("pathlib").Path(row[1]).read_bytes() == b"ready"


def test_queue_worker_failure_does_not_block_next_task(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "db.sqlite"
    first = enqueue(db_path, "first")
    second = enqueue(db_path, "second")

    async def processor(workspace, task_id):
        if task_id == first:
            raise RuntimeError("expected failure")
        (workspace / "ready.mp4").write_bytes(b"ready")
        return "ready.mp4"

    async def run():
        kwargs = dict(
            db_path=db_path, configured_download_dir=str(root),
            expected_bytes=1, processor=processor,
            max_wait_minutes=30, reserve_bytes=0,
        )
        return await process_next_queued_task(**kwargs), await process_next_queued_task(**kwargs)

    assert asyncio.run(run()) == (first, second)
    with database(db_path) as db:
        rows = db.execute("SELECT id,status FROM tasks ORDER BY id").fetchall()
    assert rows == [(first, "failed"), (second, "upload_pending")]


def test_queue_worker_stops_without_tasks(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    stop = asyncio.Event()

    async def processor(workspace, task_id):
        raise AssertionError("no tasks expected")

    async def run():
        stop.set()
        await run_queue_worker(
            stop=stop, db_path=tmp_path / "db.sqlite",
            configured_download_dir=str(root), expected_bytes=1,
            processor=processor, max_wait_minutes=30,
            reserve_bytes=0, idle_seconds=0.01,
        )

    asyncio.run(run())
