"""Selected video quality is exact, with no silent downscale fallback."""
from pathlib import Path

import pytest

from bot.downloader import DownloadError, build_command


URL = "https://www.youtube.com/watch?v=abcdefghijk"


@pytest.mark.parametrize("quality,height", [
    ("480p", 480), ("720p", 720), ("1080p", 1080),
])
def test_selected_quality_requires_exact_height(quality, height, tmp_path):
    command = build_command(URL, quality, 50_000_000, tmp_path)
    selector = command[command.index("--format") + 1]
    assert selector.count(f"height={height}") == 3
    assert "--merge-output-format" in command
    assert command[command.index("--merge-output-format") + 1] == "mp4"
    assert command[-2:] == ["--", URL]


@pytest.mark.parametrize("mode", ["360p", "2160p", "audio", "720P", ""])
def test_unsupported_quality_rejected(mode, tmp_path):
    with pytest.raises(DownloadError):
        build_command(URL, mode, 50_000_000, tmp_path)


def test_mp3_path_unchanged(tmp_path):
    command = build_command(URL, "mp3", 50_000_000, tmp_path)
    assert command[command.index("--audio-format") + 1] == "mp3"
