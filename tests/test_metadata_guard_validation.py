"""Guard command contract tests; not a substitute for OS-level egress isolation."""
import asyncio

import pytest

from bot import metadata_process
from bot.metadata_process import MetadataProcessError


@pytest.mark.parametrize("guard", [
    lambda command: command,
    lambda command: [],
    lambda command: ["wrapper", "", *command],
    lambda command: ["wrapper", "bad\x00arg", *command],
    lambda command: "wrapper",
])
def test_rejects_noop_or_invalid_network_guard(monkeypatch, guard):
    import bot.network_security as security
    monkeypatch.setattr(security, "validate_public_https_target",
                        lambda url, *, allowed_hosts: ("8.8.8.8",))
    launched = []

    async def runner(*args, **kwargs):
        launched.append(args)
        return {}

    monkeypatch.setattr(metadata_process, "run_json_subprocess", runner)
    with pytest.raises(MetadataProcessError, match="изоляция"):
        asyncio.run(metadata_process.inspect_in_subprocess(
            "https://youtu.be/abc", timeout_seconds=3, network_guard=guard,
        ))
    assert launched == []
