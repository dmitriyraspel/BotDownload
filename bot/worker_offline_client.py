"""Broker-side fixed offline result transfer; never accept worker-supplied paths."""
import asyncio
import base64
import binascii
import json
from pathlib import Path

from .worker_ipc import WorkerProtocolError
from .worker_reservations import valid_token

EXPECTED = b"offline-worker-ok"


async def execute_offline_ipc(socket_path: Path, task_id: int, token: str,
                              *, timeout: float = 15.0) -> bytes:
    if (not isinstance(socket_path, Path) or not socket_path.is_absolute()
            or type(task_id) is not int or not 0 < task_id <= 9223372036854775807
            or not valid_token(token) or type(timeout) not in (int, float)
            or not 0 < timeout <= 30):
        raise WorkerProtocolError("Некорректные параметры офлайн-IPC")
    try:
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_unix_connection(str(socket_path), limit=4096)
            try:
                request = json.dumps({
                    "op": "execute_offline", "version": 1,
                    "task_id": task_id, "token": token,
                }, separators=(",", ":")).encode() + b"\n"
                writer.write(request)
                await writer.drain()
                raw = await reader.readline()
                if not raw.endswith(b"\n") or len(raw) > 4096:
                    raise WorkerProtocolError("Некорректный ответ")
                response = json.loads(raw, object_pairs_hook=_unique)
                if (type(response) is not dict or
                        set(response) != {"version", "status", "downloads_enabled",
                                          "filename", "data"} or
                        response["version"] != 1 or
                        response["status"] != "completed" or
                        response["downloads_enabled"] is not False or
                        response["filename"] != "offline-result.bin" or
                        type(response["data"]) is not str):
                    raise WorkerProtocolError("Worker не завершил офлайн-задачу")
                payload = base64.b64decode(response["data"], validate=True)
                if payload != EXPECTED:
                    raise WorkerProtocolError("Неожиданный результат")
                return payload
            finally:
                writer.close()
                await writer.wait_closed()
    except (OSError, asyncio.TimeoutError, ValueError, UnicodeError,
            binascii.Error, asyncio.LimitOverrunError) as exc:
        raise WorkerProtocolError("Офлайн-IPC не выполнен") from exc


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WorkerProtocolError("Повторяющийся ключ")
        result[key] = value
    return result
