"""Metadata DNS preflight is defense in depth, not socket isolation."""
import asyncio

import pytest

from bot import metadata
from bot.network_security import UnsafeNetworkTarget


def test_metadata_rejects_unsafe_dns_before_extraction(monkeypatch):
    invoked = []

    def unsafe(url, *, allowed_hosts):
        raise UnsafeNetworkTarget("private")

    monkeypatch.setattr(metadata, "validate_public_https_target", unsafe)
    monkeypatch.setattr(metadata, "_extract", lambda url: invoked.append(url))
    with pytest.raises(metadata.AnalysisError, match="Небезопасный"):
        asyncio.run(metadata.inspect("https://youtu.be/abc"))
    assert invoked == []


def test_metadata_allows_preflight_then_extracts(monkeypatch):
    seen = []

    def public(url, *, allowed_hosts):
        seen.append(("dns", url))
        return ("8.8.8.8",)

    def extract(url):
        seen.append(("extract", url))
        return {"title": "test"}

    monkeypatch.setattr(metadata, "validate_public_https_target", public)
    monkeypatch.setattr(metadata, "_extract", extract)
    result = asyncio.run(metadata.inspect("https://youtu.be/abc"))
    assert result["title"] == "test"
    assert seen == [
        ("dns", "https://youtu.be/abc"),
        ("extract", "https://youtu.be/abc"),
    ]
