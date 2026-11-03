from bot.telegram_handlers import validate_media_url


def test_supported_links():
    assert validate_media_url("https://www.youtube.com/watch?v=abc")
    assert validate_media_url("https://youtu.be/abc")
    assert validate_media_url("https://www.instagram.com/reel/abc/")
    assert validate_media_url("https://www.tiktok.com/@x/video/123")


def test_rejected_links():
    bad = [
        "http://youtube.com/watch?v=abc",
        "https://example.com/",
        "https://youtube.com.evil.com/watch",
        "https://youtube.com@evil.com/watch",
        "https://evil.com@youtube.com/watch",
        "https://youtube.com:8080/watch",
        "https://youtube.com/#fragment",
        "https://youtube.com/%0a",
        "https://127.0.0.1/",
        "https://youtube.com\\@evil.com/",
        "https://youtube.com/watch?v=abc https://example.com",
    ]
    for url in bad:
        assert not validate_media_url(url), url

def test_unlisted_subdomains_rejected():
    assert not validate_media_url("https://private.youtube.com/watch?v=x")
    assert not validate_media_url("https://attacker.instagram.com/reel/x")
    assert validate_media_url("https://m.tiktok.com/@x/video/123")
    assert not validate_media_url("https://vm.tiktok.com/abc")
    assert not validate_media_url("https://vt.tiktok.com/abc")
