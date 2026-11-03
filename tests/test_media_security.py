import ipaddress
import socket

import pytest

from bot.network_security import UnsafeNetworkTarget, validate_public_https_target, validate_redirect_chain
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


def test_rejects_redirect_to_private_address(monkeypatch):
    def dns(host, *args, **kwargs):
        address = "127.0.0.1" if host == "internal.example" else "8.8.8.8"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    with pytest.raises(UnsafeNetworkTarget):
        validate_redirect_chain([
            "https://youtu.be/abc",
            "https://internal.example/private",
        ])


def test_rejects_too_many_redirects(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
    ])
    with pytest.raises(UnsafeNetworkTarget):
        validate_redirect_chain(["https://youtu.be/a"] * 7)


def test_rejects_control_character_and_backslash_urls(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
    ])
    for url in ("https://youtu.be/a" + chr(127), "https://youtu.be/a" + chr(92) + "b"):
        with pytest.raises(UnsafeNetworkTarget):
            validate_public_https_target(url)


def test_ffmpeg_rejects_input_symlink(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    source = root / "source.mp4"
    source.write_bytes(b"data")
    link = root / "link.mp4"
    try:
        link.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable on this system")
    with pytest.raises(MediaProcessingError):
        validate_local_media_file(link, root)
