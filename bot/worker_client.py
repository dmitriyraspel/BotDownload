"""Read-only worker task-status client. No command execution or file paths sent."""
import asyncio
import json
from pathlib import Path

from .worker_ipc import MAX_MESSAGE, WorkerProtocolError


async def query_task_status(socket_path: Path, task_id: int, *, timeout: float = 3.0) -> str:
    if type(task_id) is not int or not 0 < task_id <= 9223372036854775807:
        raise WorkerProtocolError("Недопустимый ID задачи")
    if not isinstance(socket_path, Path) or not socket_path.is_absolute():
        raise WorkerProtocolError("Недопустимый путь сокета")
    import math
    if (type(timeout) not in (int, float) or not math.isfinite(timeout)
            or timeout <= 0):
        raise WorkerProtocolError("Недопустимый тайм-аут")
    try:
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_unix_connection(str(socket_path))
            try:
                payload = json.dumps(
                    {"op": "task_status", "version": 1, "task_id": task_id},
                    separators=(",", ":"),
                ).encode() + b"\n"
                writer.write(payload)
                await writer.drain()
                raw = await reader.readline()
                if not raw.endswith(b"\n") or len(raw) > MAX_MESSAGE:
                    raise WorkerProtocolError("Некорректный ответ worker")
                result = json.loads(raw)
                allowed = {"queued", "downloading", "processing", "upload_pending",
                           "uploading", "completed", "failed", "cancelled",
                           "missing", "unavailable"}
                if (type(result) is not dict or set(result) != {
                    "version", "status", "task_status", "downloads_enabled",
                } or type(result["version"]) is not int or result["version"] != 1
                        or result["status"] != "ok"
                        or result["downloads_enabled"] is not False
                        or result["task_status"] not in allowed):
                    raise WorkerProtocolError("Недостоверный ответ worker")
                return result["task_status"]
            finally:
                writer.close()
                await writer.wait_closed()
    except (OSError, asyncio.TimeoutError, UnicodeError, ValueError) as exc:
        raise WorkerProtocolError("Worker недоступен или ответ некорректен") from exc
