from bot.storage import database, create_task, change_status, cancel_user_tasks, record_delivery


def test_duplicate_callback_does_not_duplicate_task(tmp_path):
    with database(tmp_path / "state.sqlite") as db:
        params = dict(user_id=123, chat_id=123, message_id=42,
                      callback_key="123:42:720p", source_url="https://youtu.be/x",
                      media_key="youtube:x", variant="720p")
        first, created = create_task(db, **params)
        assert created
        again, created = create_task(db, **params)
        assert first == again and not created
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_status_transitions_and_user_cancel(tmp_path):
    with database(tmp_path / "state.sqlite") as db:
        def add(user):
            return create_task(db, user_id=user, chat_id=user, message_id=user,
                               callback_key=str(user), source_url="https://youtu.be/x",
                               media_key="youtube:x", variant="720p")[0]
        a, b = add(1), add(2)
        assert not change_status(db, a, "queued", "completed")
        assert change_status(db, a, "queued", "downloading")
        assert cancel_user_tasks(db, 1) == 1
        assert not change_status(db, a, "downloading", "processing")
        assert db.execute("SELECT status FROM tasks WHERE id=?", (b,)).fetchone()[0] == "queued"


def test_successful_delivery_charges_only_once(tmp_path):
    with database(tmp_path / "state.sqlite") as db:
        task, _ = create_task(db, user_id=7, chat_id=7, message_id=7,
                              callback_key="a", source_url="https://youtu.be/x",
                              media_key="youtube:x", variant="MP3")
        assert change_status(db, task, "queued", "downloading")
        assert change_status(db, task, "downloading", "processing")
        assert change_status(db, task, "processing", "upload_pending")
        assert change_status(db, task, "upload_pending", "uploading")
        assert record_delivery(db, task, "telegram-file", "2026-11-03", cache_hit=False)
        assert not record_delivery(db, task, "telegram-file", "2026-11-03", cache_hit=False)
        assert db.execute("SELECT COUNT(*) FROM daily_usage").fetchone()[0] == 1
        assert cancel_user_tasks(db, 7) == 0


def test_cached_delivery_does_not_charge_quota(tmp_path):
    with database(tmp_path / "state.sqlite") as db:
        task, _ = create_task(db, user_id=7, chat_id=7, message_id=7,
                              callback_key="cached", source_url="https://youtu.be/x",
                              media_key="youtube:x", variant="720p")
        for source, target in (("queued", "downloading"),
                               ("downloading", "processing"),
                               ("processing", "upload_pending"),
                               ("upload_pending", "uploading")):
            assert change_status(db, task, source, target)
        assert record_delivery(db, task, "file-id", "2026-11-03", cache_hit=True)
        assert db.execute("SELECT COUNT(*) FROM daily_usage").fetchone()[0] == 0
