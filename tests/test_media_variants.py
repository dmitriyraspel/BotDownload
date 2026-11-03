from bot.media_variants import available_variants, selected_language, size_label


def test_only_real_qualities_are_offered():
    info = {"formats": [
        {"height": 720, "vcodec": "avc1", "acodec": "none", "filesize": 10_485_760},
        {"height": 360, "vcodec": "avc1", "acodec": "none"},
        {"vcodec": "none", "acodec": "mp4a", "language": "ru"},
    ]}
    variants = available_variants(info)
    assert [v["quality"] for v in variants] == ["720p", "MP3"]
    assert variants[0]["approximate"] is True  # video-only size excludes audio
    assert variants[1]["size"] is None
    assert selected_language(info) == "Русский"


def test_unknown_language_and_sizes_are_not_invented():
    assert selected_language({"formats": []}) == "Язык аудио не определён"
    assert available_variants({"formats": []}) == []
    assert size_label(None, True) == "размер неизвестен"
    assert size_label(1048576, False) == "1.0 МиБ"
