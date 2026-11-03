"""Security tests for central media admission."""
import pytest

from bot.media_admission import AdmissionDenied, admit_inspect, admit_download
from bot.storage import database, save_preview, enqueue_task


def test_inspect_admits_only_platform_url():
    assert admit_inspect("https://www.youtube.com/watch?v=abc").url.startswith("https:")
    with pytest.raises(AdmissionDenied):
        admit_inspect("https://127.0.0.1/")


def test_button_uses_immutable_saved_card(tmp_path):
    path = tmp_path / "tasks.sqlite"
    url = "https://www.youtube.com/watch?v=abc"
    with database(path) as db:
        save_preview(db, chat_id=11, message_id=22, user_id=33,
                     source_url=url, media_key="youtube:abc", variants=["480p"])
        task, created = enqueue_task(
            db, max_pending=10, user_id=33, chat_id=11, message_id=22,
            callback_key="11:22:33:480p", source_url=url,
            media_key="youtube:abc", variant="480p")
        assert created
        approved = admit_download(db, task_id=task)
        assert approved.url == url and approved.quality == "480p"
        db.execute("UPDATE tasks SET source_url=? WHERE id=?",
                   ("https://www.tiktok.com/@other/video/2", task))
        with pytest.raises(AdmissionDenied):
            admit_download(db, task_id=task)


def test_foreign_or_cancelled_card_is_rejected(tmp_path):
    with database(tmp_path / "tasks.sqlite") as db:
        url = "https://www.youtube.com/watch?v=abc"
        save_preview(db, chat_id=11, message_id=22, user_id=33,
                     source_url=url, media_key="youtube:abc", variants=["720p"])
        task, _ = enqueue_task(
            db, max_pending=10, user_id=33, chat_id=11, message_id=22,
            callback_key="11:22:33:720p", source_url=url,
            media_key="youtube:abc", variant="720p")
        db.execute("UPDATE previews SET cancelled=1 WHERE chat_id=11")
        with pytest.raises(AdmissionDenied):
            admit_download(db, task_id=task)
