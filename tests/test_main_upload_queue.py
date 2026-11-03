import asyncio
from types import SimpleNamespace

from bot import main as entrypoint


def test_run_bot_starts_and_stops_upload_queue(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    events = []

    class Session:
        async def close(self):
            events.append("session_closed")

    class Bot:
        def __init__(self, *, token, session=None):
            self.session = Session()

    class Dispatcher:
        def include_router(self, router):
            pass

        async def start_polling(self, bot):
            events.append("polling")
            await asyncio.sleep(0.01)

    async def fake_upload_queue(*, stop, **kwargs):
        events.append("upload_started")
        await stop.wait()
        events.append("upload_stopped")

    monkeypatch.setattr(entrypoint, "Bot", Bot)
    monkeypatch.setattr(entrypoint, "Dispatcher", Dispatcher)
    monkeypatch.setattr(entrypoint, "run_upload_queue", fake_upload_queue)
    settings = SimpleNamespace(token="test-token", data={
        "telegram": {
            "api_mode": "cloud",
            "max_upload_size_mb": {"cloud": 50, "local": 2000},
        },
        "storage": {"download_dir": str(tmp_path)},
        "limits": {"daily_download_limit": 3},
        "trusted_users": [],
        "telegram_upload_max_attempts": 3,
        "telegram_upload_second_attempt_delay_seconds": 5,
        "telegram_upload_third_attempt_delay_seconds": 10,
    })
    asyncio.run(entrypoint.run_bot(settings))
    assert events == ["polling", "upload_started", "upload_stopped", "session_closed"]
