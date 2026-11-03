"""Broker-side IPC dispatch: reserve and revoke, never execute downloads."""
import asyncio
import json
import math
from pathlib import Path

from .worker_ipc import WorkerProtocolError
from .worker_reservations import valid_token


async def _request(socket_path: Path, task_id: int, token: str, op: str,
                   timeout: float) -> bool:
    if (not isinstance(socket_path, Path) or not socket_path.is_absolute()
            or type(task_id) is not int or not 0 < task_id <= 9223372036854775807
            or not valid_token(token) or op not in ("reserve", "cancel_reservation")
            or type(timeout) not in (int, float) or not math.isfinite(timeout)
            or timeout <= 0):
        raise WorkerProtocolError("Некорректные параметры IPC")
    try:
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_unix_connection(str(socket_path))
            try:
                request = json.dumps(
                    {"op": op, "version": 1, "task_id": task_id, "token": token},
                    separators=(",", ":"),
                ).encode() + b"\n"
                writer.write(request)
                await writer.drain()
                response = await reader.readline()
                if len(response) > 4096 or not response.endswith(b"\n"):
                    raise WorkerProtocolError("Некорректный ответ worker")
                result = json.loads(response)
                if (type(result) is not dict
                        or set(result) != {"version", "status", "downloads_enabled"}
                        or type(result["version"]) is not int or result["version"] != 1
                        or result["downloads_enabled"] is not False
                        or result["status"] not in ("accepted", "rejected")):
                    raise WorkerProtocolError("Недостоверный ответ worker")
                return result["status"] == "accepted"
            finally:
                writer.close()
                await writer.wait_closed()
    except (OSError, asyncio.TimeoutError, ValueError, UnicodeError) as exc:
        raise WorkerProtocolError("IPC worker недоступен") from exc


async def reserve_worker_job(socket_path: Path, task_id: int, token: str,
                             *, timeout: float = 3.0) -> bool:
    return await _request(socket_path, task_id, token, "reserve", timeout)


async def cancel_worker_reservation(socket_path: Path, task_id: int, token: str,
                                    *, timeout: float = 3.0) -> bool:
    return await _request(socket_path, task_id, token, "cancel_reservation", timeout)
