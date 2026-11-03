from unittest.mock import patch
from bot.storage import database, create_task, change_status, mark_file_ready, reserve_delivery_slot
from bot.upload_admin import main


def setup(path):
    with database(path) as db:
        task, _ = create_task(db, user_id=11, chat_id=12, message_id=13,
                              callback_key="admin", source_url="https://youtu.be/x",
                              media_key="x", variant="MP3")
        assert change_status(db, task, "queued", "downloading")
        assert change_status(db, task, "downloading", "processing")
        assert mark_file_ready(db, task, "/staged/audio.mp3")
        assert reserve_delivery_slot(db, task_id=task, utc_day="2026-11-03", daily_limit=3)
        assert change_status(db, task, "upload_pending", "uploading")
    return task


def test_noninteractive_refusal(tmp_path):
    path = tmp_path / "db.sqlite"
    task = setup(path)
    with patch("bot.upload_admin.sys.stdin.isatty", return_value=False):
        assert main(["--db", str(path), "--task-id", str(task), "--not-delivered"]) == 2
    with database(path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?", (task,)).fetchone()[0] == "uploading"


def test_confirmation_mismatch(tmp_path):
    path = tmp_path / "db.sqlite"
    task = setup(path)
    with patch("bot.upload_admin.sys.stdin.isatty", return_value=True):
        with patch("builtins.input", return_value="wrong"):
            assert main(["--db", str(path), "--task-id", str(task), "--not-delivered"]) == 1
    with database(path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?", (task,)).fetchone()[0] == "uploading"


def test_confirmed_non_delivery(tmp_path):
    path = tmp_path / "db.sqlite"
    task = setup(path)
    with patch("bot.upload_admin.sys.stdin.isatty", return_value=True):
        with patch("builtins.input", return_value=f"CONFIRM {task}"):
            assert main(["--db", str(path), "--task-id", str(task), "--not-delivered"]) == 0
    with database(path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?", (task,)).fetchone()[0] == "upload_pending"


def test_confirmed_delivery(tmp_path):
    path = tmp_path / "db.sqlite"
    task = setup(path)
    with patch("bot.upload_admin.sys.stdin.isatty", return_value=True):
        with patch("builtins.input", return_value=f"CONFIRM {task}"):
            with patch("bot.upload_admin.getpass.getpass", return_value="file-id"):
                assert main(["--db", str(path), "--task-id", str(task), "--delivered"]) == 0
    with database(path) as db:
        assert db.execute("SELECT status,telegram_file_id FROM tasks WHERE id=?", (task,)).fetchone() == ("completed", "file-id")
