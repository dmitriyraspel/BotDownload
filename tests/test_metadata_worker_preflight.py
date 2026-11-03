"""Metadata child validates literal URL without rejecting router Fake-IP DNS."""
from unittest.mock import patch
from bot.metadata_worker import main

def test_child_extracts_approved_url_without_dns_preflight(capsys):
    with patch("bot.metadata_worker._extract", return_value={"title": "ok"}) as extract:
        assert main(["https://youtu.be/abc"]) == 0
        extract.assert_called_once_with("https://youtu.be/abc")
    assert '"title": "ok"' in capsys.readouterr().out

def test_child_rejects_bad_url_before_extractor():
    with patch("bot.metadata_worker._extract") as extract:
        assert main(["http://127.0.0.1/"]) == 2
        extract.assert_not_called()

def test_child_hides_extractor_error(capsys):
    with patch("bot.metadata_worker._extract", side_effect=RuntimeError("secret")):
        assert main(["https://youtu.be/abc"]) == 1
    assert capsys.readouterr().out == ""
