"""Minimal Unix-socket IPC for a separately installed system worker.

The protocol intentionally has NO download or shell-execution operation.
Deployment must validate kernel egress confinement before adding either.
"""
import asyncio
import json
import math
import os
from pathlib import Path
import socket
import struct
import stat
import sqlite3
from contextlib import closing
from .worker_reservations import JobReservations, valid_token
from .worker_offline import OfflineJobController


class WorkerProtocolError(ValueError):
    pass


MAX_MESSAGE = 4096


def _unique_json_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise WorkerProtocolError("Повторяющийся ключ JSON")
        result[key] = value
    return result


def parse_request(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_MESSAGE:
        raise WorkerProtocolError("Недопустимый размер запроса")
    try:
        request = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json_pairs)
    except (UnicodeError, ValueError) as exc:
        raise WorkerProtocolError("Некорректный JSON") from exc
    if (not isinstance(request, dict)
            or type(request.get("version")) is not int
            or request.get("version") != 1
            or not (
                (set(request) == {"op", "version"} and request.get("op") == "ping")
                or (set(request) == {"op", "version", "task_id"}
                    and request.get("op") == "task_status"
                    and type(request.get("task_id")) is int
                    and 0 < request["task_id"] <= 9223372036854775807)
                or (set(request) == {"op", "version", "task_id", "token"}
                    and request.get("op") in ("reserve", "cancel_reservation", "execute_offline", "execute_media")
                    and type(request.get("task_id")) is int
                    and 0 < request["task_id"] <= 9223372036854775807
                    and valid_token(request.get("token")))
            )):
        raise WorkerProtocolError("Операция не разрешена")
    return request


def task_status(db_path: Path, task_id: int) -> str:
    """Read a task from SQLite without executing it or mutating queue state."""
    if (not isinstance(db_path, Path) or not db_path.is_absolute()
            or type(task_id) is not int or task_id <= 0):
        return "unavailable"
    try:
        from urllib.parse import quote
        uri = "file:" + quote(str(db_path), safe="/") + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=1)) as db:
            db.execute("PRAGMA query_only=ON")
            row = db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            return "missing"
        return row[0] if row[0] in (
            "queued", "downloading", "processing", "upload_pending",
            "uploading", "completed", "failed", "cancelled",
        ) else "unavailable"
    except (sqlite3.Error, OSError):
        return "unavailable"


def peer_uid(writer: asyncio.StreamWriter) -> int:
    """Read kernel-verified Unix peer credentials; never trust a claimed UID."""
    sock = writer.get_extra_info("socket")
    if sock is None or not hasattr(socket, "SO_PEERCRED"):
        raise WorkerProtocolError("Проверка клиента недоступна")
    try:
        raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", raw)
    except (OSError, ValueError, struct.error) as exc:
        raise WorkerProtocolError("Не удалось проверить клиента") from exc
    return uid


async def handle_connection(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *,
    allowed_uid: int, db_path: Path | None = None,
    reservations: JobReservations | None = None,
    offline: OfflineJobController | None = None,
    media=None,
) -> None:
    try:
        if type(allowed_uid) is not int or allowed_uid < 0:
            raise WorkerProtocolError("Не настроен UID клиента")
        if peer_uid(writer) != allowed_uid:
            raise WorkerProtocolError("Доступ запрещён")
        raw = await asyncio.wait_for(reader.readline(), timeout=3)
        if not raw.endswith(b"\n") or len(raw) > MAX_MESSAGE + 1:
            raise WorkerProtocolError("Недопустимая длина сообщения")
        request = parse_request(raw[:-1])
        if request["op"] == "ping":
            response = {"version": 1, "status": "ready", "downloads_enabled": False}
        elif request["op"] == "execute_media":
            response = (await media.execute(db_path, request["task_id"], request["token"])
                        if media is not None else
                        {"version": 1, "status": "rejected", "downloads_enabled": False})
        elif request["op"] == "execute_offline":
            response = (await offline.execute(db_path, request["task_id"], request["token"])
                        if offline is not None else
                        {"version": 1, "status": "rejected", "downloads_enabled": False})
        elif request["op"] in ("reserve", "cancel_reservation"):
            if reservations is None:
                accepted = False
            elif request["op"] == "reserve":
                accepted = reservations.accept(db_path, request["task_id"], request["token"])
            else:
                accepted = (offline.cancel(request["task_id"], request["token"])
                            if offline is not None else
                            reservations.cancel(request["task_id"], request["token"]))
            response = {"version": 1, "status": "accepted" if accepted else "rejected",
                        "downloads_enabled": False}
        else:
            response = {
                "version": 1, "status": "ok",
                "task_status": task_status(db_path, request["task_id"]),
                "downloads_enabled": False,
            }
    except (WorkerProtocolError, asyncio.TimeoutError, asyncio.LimitOverrunError, ValueError):
        response = {"version": 1, "status": "rejected"}
    try:
        writer.write(json.dumps(response, separators=(",", ":")).encode() + b"\n")
        await asyncio.wait_for(writer.drain(), timeout=3)
    except (OSError, ConnectionError, asyncio.TimeoutError):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (OSError, ConnectionError):
            pass


async def serve(socket_path: Path, *, allowed_uid: int, db_path: Path | None = None) -> None:
    """Serve on a socket path owned by a root-created, private runtime dir."""
    if (not isinstance(socket_path, Path) or not socket_path.is_absolute()
            or type(allowed_uid) is not int or allowed_uid < 0):
        raise WorkerProtocolError("Неверная конфигурация сокета")
    parent = socket_path.parent
    try:
        parent_info = parent.lstat()
    except OSError as exc:
        raise WorkerProtocolError("Каталог сокета отсутствует") from exc
    if (not stat.S_ISDIR(parent_info.st_mode)
            or parent_info.st_uid != os.geteuid()
            or parent_info.st_mode & 0o002):
        raise WorkerProtocolError("Каталог сокета отсутствует или небезопасен")
    if socket_path.exists() or socket_path.is_symlink():
        raise WorkerProtocolError("Сокет уже существует")
    reservations = JobReservations()
    offline = OfflineJobController(reservations)
    from .worker_media import MediaJobController
    media = MediaJobController(reservations)
    server = await asyncio.start_unix_server(
        lambda r, w: handle_connection(r, w, allowed_uid=allowed_uid, db_path=db_path, reservations=reservations, offline=offline, media=media),
        path=str(socket_path), limit=MAX_MESSAGE + 2,
    )
    try:
        os.chmod(socket_path, 0o660)
        async with server:
            await server.serve_forever()
    finally:
        server.close()
        await server.wait_closed()
        try:
            if socket_path.is_socket():
                socket_path.unlink()
        except OSError:
            pass


async def ping(socket_path: Path, *, timeout: float = 3.0) -> bool:
    """Fail closed: an IPC ping is not proof of egress isolation."""
    if (not isinstance(socket_path, Path) or not socket_path.is_absolute()
            or isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        return False
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(socket_path)), timeout=timeout,
        )
        try:
            writer.write(b'{"op":"ping","version":1}\n')
            await asyncio.wait_for(writer.drain(), timeout=timeout)
            response = await asyncio.wait_for(reader.readline(), timeout=timeout)
            return response == b'{"version":1,"status":"ready","downloads_enabled":false}\n'
        finally:
            writer.close()
            await writer.wait_closed()
    except (OSError, asyncio.TimeoutError, ValueError, ConnectionError):
        return False
