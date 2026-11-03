"""Ambiguous delivery reporting must never mutate persistent state."""
import json

from bot.storage import (database, create_task, change_status,
                         mark_file_ready, reserve_delivery_slot)
from bot.upload_reconciliation import ambiguous_uploads, main


def test_ambiguous_report_is_read_only(tmp_path, capsys):
    path = tmp_path / "state.sqlite"
    with database(path) as db:
        task, _ = create_task(
            db, user_id=91, chat_id=92, message_id=93,
            callback_key="upload-91", source_url="https://youtu.be/secret",
            media_key="secret", variant="MP3")
        for a, b in (("queued", "downloading"), ("downloading", "processing")):
            assert change_status(db, task, a, b)
        assert mark_file_ready(db, task, "/staged/file.mp3")
        assert reserve_delivery_slot(db, task_id=task, utc_day="2026-11-03",
                                     daily_limit=3)
        assert change_status(db, task, "upload_pending", "uploading")
    records = ambiguous_uploads(path)
    assert len(records) == 1
    assert records[0]["task_id"] == task
    assert records[0]["reserved_utc_day"] == "2026-11-03"
    assert records[0]["has_staged_file"]
    assert "source_url" not in records[0]
    assert "ready_file" not in records[0]
    assert main(["--db", str(path), "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ambiguous_uploads"] == records
    with database(path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?",
                          (task,)).fetchone()[0] == "uploading"
        assert db.execute("SELECT COUNT(*) FROM delivery_reservations").fetchone()[0] == 1


def test_empty_report(tmp_path, capsys):
    path = tmp_path / "state.sqlite"
    with database(path):
        pass
    assert ambiguous_uploads(path) == []
    assert main(["--db", str(path)]) == 0
    assert "Нет отправок" in capsys.readouterr().out
