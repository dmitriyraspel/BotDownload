"""Durable queue reads and UTC quota preflight."""
import sqlite3

import pytest

from bot.storage import (database, create_task, get_task, quota_available,
                         count_daily_deliveries, change_status, record_delivery)


def _new_task(db, key):
    task_id, created = create_task(
        db, user_id=42, chat_id=42, message_id=1, callback_key=key,
        source_url="https://youtu.be/example", media_key="example", variant="720p")
    assert created
    return task_id


def test_get_task_is_safe_and_preserves_row_factory(tmp_path):
    with database(tmp_path / "state.sqlite") as db:
        task_id = _new_task(db, "first")
        db.row_factory = sqlite3.Row
        item = get_task(db, task_id)
        assert item["id"] == task_id
        assert item["status"] == "queued"
        assert item["variant"] == "720p"
        assert db.row_factory is sqlite3.Row
        assert get_task(db, -1) is None
        assert get_task(db, 9999) is None


def test_quota_counts_only_successful_uncached_deliveries(tmp_path):
    with database(tmp_path / "state.sqlite") as db:
        task_id = _new_task(db, "first")
        assert quota_available(db, user_id=42, utc_day="2026-11-03", daily_limit=1)
        assert change_status(db, task_id, "queued", "downloading")
        assert change_status(db, task_id, "downloading", "processing")
        assert change_status(db, task_id, "processing", "upload_pending")
        assert change_status(db, task_id, "upload_pending", "uploading")
        assert record_delivery(db, task_id, "file-id", "2026-11-03", cache_hit=False)
        assert count_daily_deliveries(db, user_id=42, utc_day="2026-11-03") == 1
        assert not quota_available(db, user_id=42, utc_day="2026-11-03", daily_limit=1)
        assert quota_available(db, user_id=42, utc_day="2026-11-03",
                               daily_limit=1, trusted_users=[42])
        assert quota_available(db, user_id=42, utc_day="2026-11-04", daily_limit=1)


def test_quota_rejects_invalid_date_and_limit(tmp_path):
    with database(tmp_path / "state.sqlite") as db:
        with pytest.raises(ValueError):
            count_daily_deliveries(db, user_id=42, utc_day="yesterday")
        with pytest.raises(ValueError):
            quota_available(db, user_id=42, utc_day="2026-11-03", daily_limit=0)
