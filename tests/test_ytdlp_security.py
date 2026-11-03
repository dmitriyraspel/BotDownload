import socket

import pytest

from bot.network_security import UnsafeNetworkTarget
from bot.ytdlp_security import audit_extracted_media_urls


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
    ])


def test_audit_allows_public_https_formats(public_dns):
    info = {"formats": [
        {"protocol": "https", "url": "https://cdn.example/video.mp4"},
        {"protocol": "https", "url": "https://cdn.example/audio.m4a"},
    ]}
    assert audit_extracted_media_urls(info) == 2


@pytest.mark.parametrize("entry", [
    {"protocol": "http", "url": "http://cdn.example/video.mp4"},
    {"protocol": "file", "url": "file:///etc/passwd"},
    {"protocol": "https", "url": "https://127.0.0.1/video"},
    {"protocol": "m3u8_native", "url": "https://cdn.example/playlist.m3u8"},
])
def test_audit_rejects_unsafe_formats(public_dns, entry):
    with pytest.raises(UnsafeNetworkTarget):
        audit_extracted_media_urls({"formats": [entry]})


def test_audit_rejects_excessive_formats(public_dns):
    with pytest.raises(UnsafeNetworkTarget):
        audit_extracted_media_urls({"formats": [{}] * 501})
