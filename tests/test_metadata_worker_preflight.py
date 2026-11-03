"""Metadata child performs its own DNS validation before extraction."""
from unittest.mock import patch

from bot.metadata_worker import main
from bot.network_security import UnsafeNetworkTarget


def test_child_rejects_private_resolution_before_extractor():
    with patch("bot.metadata_worker.validate_public_https_target",
               side_effect=UnsafeNetworkTarget("private")) as preflight, \
         patch("bot.metadata_worker._extract") as extract:
        assert main(["https://youtu.be/abc"]) == 1
        preflight.assert_called_once()
        extract.assert_not_called()


def test_child_extracts_only_after_validated_resolution(capsys):
    with patch("bot.metadata_worker.validate_public_https_target") as preflight, \
         patch("bot.metadata_worker._extract", return_value={"title": "ok"}) as extract:
        assert main(["https://youtu.be/abc"]) == 0
        preflight.assert_called_once()
        extract.assert_called_once_with("https://youtu.be/abc")
    assert '"title": "ok"' in capsys.readouterr().out


def test_child_rejects_bad_url_before_network_or_extractor():
    with patch("bot.metadata_worker.validate_public_https_target") as preflight, \
         patch("bot.metadata_worker._extract") as extract:
        assert main(["http://127.0.0.1/"]) == 2
        preflight.assert_not_called()
        extract.assert_not_called()
