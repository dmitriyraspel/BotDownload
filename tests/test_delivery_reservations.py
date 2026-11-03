"""Pre-upload quota reservations are durable and serialized."""
from bot.storage import (
    database, create_task, change_status, reserve_delivery_slot,
    release_delivery_slot, complete_reserved_delivery, count_daily_deliveries,
)


def _pending(db, key):
    task, _ = create_task(db, user_id=17, chat_id=17, message_id=17,
                          callback_key=key, source_url="https://youtu.be/x",
                          media_key="x", variant="720p")
    for a, b in (("queued", "downloading"), ("downloading", "processing"),
                 ("processing", "upload_pending")):
        assert change_status(db, task, a, b)
    return task


def test_reservation_prevents_second_upload_before_delivery(tmp_path):
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        first = _pending(db, "one")
        second = _pending(db, "two")
        assert reserve_delivery_slot(db, task_id=first, utc_day="2026-11-03",
                                     daily_limit=1)
    with database(path) as db:
        assert not reserve_delivery_slot(db, task_id=second,
                                         utc_day="2026-11-03", daily_limit=1)
        assert reserve_delivery_slot(db, task_id=first,
                                     utc_day="2026-11-03", daily_limit=1)
        assert change_status(db, first, "upload_pending", "uploading")
        assert complete_reserved_delivery(db, task_id=first,
                                          telegram_file_id="file1")
        assert not complete_reserved_delivery(db, task_id=first,
                                              telegram_file_id="file1")
        assert count_daily_deliveries(db, user_id=17, utc_day="2026-11-03") == 1
        assert not reserve_delivery_slot(db, task_id=second,
                                         utc_day="2026-11-03", daily_limit=1)


def test_release_after_failed_upload_frees_slot(tmp_path):
    with database(tmp_path / "db.sqlite") as db:
        first = _pending(db, "one")
        second = _pending(db, "two")
        assert reserve_delivery_slot(db, task_id=first, utc_day="2026-11-03",
                                     daily_limit=1)
        assert release_delivery_slot(db, first)
        assert not release_delivery_slot(db, first)
        assert reserve_delivery_slot(db, task_id=second, utc_day="2026-11-03",
                                     daily_limit=1)


def test_trusted_user_can_reserve_beyond_limit(tmp_path):
    with database(tmp_path / "db.sqlite") as db:
        first = _pending(db, "one")
        second = _pending(db, "two")
        for task in (first, second):
            assert reserve_delivery_slot(db, task_id=task, utc_day="2026-11-03",
                                         daily_limit=1, trusted_users=[17])


def test_reservation_requires_pending_task_and_valid_date(tmp_path):
    with database(tmp_path / "db.sqlite") as db:
        task, _ = create_task(db, user_id=17, chat_id=17, message_id=17,
                              callback_key="one", source_url="https://youtu.be/x",
                              media_key="x", variant="720p")
        assert not reserve_delivery_slot(db, task_id=task, utc_day="2026-11-03",
                                         daily_limit=1)
        assert not reserve_delivery_slot(db, task_id=0, utc_day="2026-11-03",
                                         daily_limit=1)
