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


def test_bitrate_estimates_combined_video_and_audio():
    info = {"duration": 100, "formats": [
        {"height": 720, "vcodec": "avc1", "acodec": "none", "tbr": 1000},
        {"vcodec": "none", "acodec": "mp4a", "abr": 128, "language": "ru"},
    ]}
    video = available_variants(info)[0]
    assert video["size"] == 14_100_000
    assert video["approximate"] is True


def test_no_estimate_without_duration_or_audio_size():
    info = {"formats": [
        {"height": 720, "vcodec": "avc1", "acodec": "none", "filesize": 10_000},
        {"vcodec": "none", "acodec": "mp4a"},
    ]}
    assert available_variants(info)[0]["size"] is None
