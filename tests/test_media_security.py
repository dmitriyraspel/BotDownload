import ipaddress
import socket

import pytest

from bot.network_security import UnsafeNetworkTarget, validate_public_https_target
from bot.ffmpeg_security import MediaProcessingError, validate_local_media_file


def test_rejects_private_dns_result(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
    ])
    with pytest.raises(UnsafeNetworkTarget):
        validate_public_https_target("https://www.youtube.com/watch?v=abc",
                                     allowed_hosts={"www.youtube.com"})


def test_rejects_mixed_public_and_private_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
    ])
    with pytest.raises(UnsafeNetworkTarget):
        validate_public_https_target("https://www.youtube.com/watch?v=abc",
                                     allowed_hosts={"www.youtube.com"})


def test_accepts_only_allowed_public_https(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
    ])
    assert validate_public_https_target("https://youtu.be/abc",
                                         allowed_hosts={"youtu.be"}) == ("8.8.8.8",)
    for url in ("http://youtu.be/abc", "https://127.0.0.1/video",
                "https://evil.example/video", "https://youtu.be@evil.example/video"):
        with pytest.raises(UnsafeNetworkTarget):
            validate_public_https_target(url, allowed_hosts={"youtu.be"})


def test_ffmpeg_rejects_files_outside_workdir(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    external = tmp_path / "outside.mp4"
    external.write_bytes(b"video")
    with pytest.raises(MediaProcessingError):
        validate_local_media_file(external, workdir)
    inside = workdir / "inside.mp4"
    inside.write_bytes(b"video")
    assert validate_local_media_file(inside, workdir) == inside.resolve()
