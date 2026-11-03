from bot.storage import database, save_preview, select_preview, cancel_preview_record


def test_preview_ownership_variants_and_cancellation(tmp_path):
    path = tmp_path / "state.sqlite"
    with database(path) as db:
        save_preview(db, chat_id=1, message_id=2, user_id=10,
                     source_url="https://youtu.be/abc", media_key="youtube:abc",
                     variants=["720p", "MP3"])
        assert select_preview(db, chat_id=1, message_id=2, user_id=10,
                              variant="720p") == ("https://youtu.be/abc", "youtube:abc")
        assert select_preview(db, chat_id=1, message_id=2, user_id=11, variant="720p") is None
        assert select_preview(db, chat_id=1, message_id=2, user_id=10, variant="1080p") is None
        assert not cancel_preview_record(db, chat_id=1, message_id=2, user_id=11)
        assert cancel_preview_record(db, chat_id=1, message_id=2, user_id=10)
        assert not cancel_preview_record(db, chat_id=1, message_id=2, user_id=10)
        assert select_preview(db, chat_id=1, message_id=2, user_id=10, variant="MP3") is None


def test_preview_survives_database_reopen(tmp_path):
    path = tmp_path / "state.sqlite"
    with database(path) as db:
        save_preview(db, chat_id=5, message_id=6, user_id=7,
                     source_url="https://youtu.be/xyz", media_key="youtube:xyz",
                     variants=["480p"])
    with database(path) as db:
        assert select_preview(db, chat_id=5, message_id=6, user_id=7,
                              variant="480p") == ("https://youtu.be/xyz", "youtube:xyz")
