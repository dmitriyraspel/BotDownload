from pathlib import Path
import pytest

from bot.downloader import DownloadError, build_command, check_duration, check_size


def test_duration_limits():
    check_duration(60, 120)
    for duration in (None, 0, -1, 121, True):
        with pytest.raises(DownloadError):
            check_duration(duration, 120)


def test_size_limits():
    check_size(1024, 2048)
    for size in (None, 0, -1, 2049, True):
        with pytest.raises(DownloadError):
            check_size(size, 2048)


def test_command_is_argument_list_without_shell():
    cmd = build_command("https://youtu.be/abc", "mp3", 10_000, Path("tmp"))
    assert cmd[-2:] == ["--", "https://youtu.be/abc"]
    assert "--extract-audio" in cmd
    assert "--ignore-config" in cmd
    assert "--max-filesize" in cmd


def test_invalid_inputs_rejected():
    for url, mode in [("https://example.com/", "mp3"), ("https://youtu.be/abc", "zip")]:
        with pytest.raises(DownloadError):
            build_command(url, mode, 10_000, Path("tmp"))


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_duration_rejected(duration):
    with pytest.raises(DownloadError):
        check_duration(duration, 120)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_duration_limit_rejected(limit):
    with pytest.raises(DownloadError):
        check_duration(60, limit)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_size_limit_rejected(limit):
    with pytest.raises(DownloadError):
        check_size(100, limit)


@pytest.mark.parametrize("limit", [True, 1.5, 0, -1])
def test_build_command_rejects_invalid_size_limit(limit):
    with pytest.raises(DownloadError, match="лимит"):
        build_command("https://youtu.be/abc", "mp3", limit, Path("tmp"))
