"""Minimal Unix-socket IPC for a separately installed system worker.

The protocol intentionally has NO download or shell-execution operation.
Deployment must validate kernel egress confinement before adding either.
"""
import asyncio
import json
import os
from pathlib import Path
import socket
import struct


class WorkerProtocolError(ValueError):
    pass


MAX_MESSAGE = 4096


def parse_request(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_MESSAGE:
        raise WorkerProtocolError("Недопустимый размер запроса")
    try:
        request = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise WorkerProtocolError("Некорректный JSON") from exc
    if (not isinstance(request, dict) or set(request) != {"op", "version"}
            or request.get("version") != 1 or type(request.get("version")) is not int
            or request.get("op") != "ping"):
        raise WorkerProtocolError("Операция не разрешена")
    return request


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
    allowed_uid: int,
) -> None:
    try:
        if type(allowed_uid) is not int or allowed_uid < 0:
            raise WorkerProtocolError("Не настроен UID клиента")
        if peer_uid(writer) != allowed_uid:
            raise WorkerProtocolError("Доступ запрещён")
        raw = await asyncio.wait_for(reader.readline(), timeout=3)
        if not raw.endswith(b"\n") or len(raw) > MAX_MESSAGE + 1:
            raise WorkerProtocolError("Недопустимая длина сообщения")
        parse_request(raw[:-1])
        response = {"version": 1, "status": "ready", "downloads_enabled": False}
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


async def serve(socket_path: Path, *, allowed_uid: int) -> None:
    """Serve on a socket path owned by a root-created, private runtime dir."""
    if (not isinstance(socket_path, Path) or not socket_path.is_absolute()
            or type(allowed_uid) is not int or allowed_uid < 0):
        raise WorkerProtocolError("Неверная конфигурация сокета")
    parent = socket_path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise WorkerProtocolError("Каталог сокета отсутствует или небезопасен")
    if socket_path.exists() or socket_path.is_symlink():
        raise WorkerProtocolError("Сокет уже существует")
    server = await asyncio.start_unix_server(
        lambda r, w: handle_connection(r, w, allowed_uid=allowed_uid),
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
    if not isinstance(socket_path, Path) or not socket_path.is_absolute():
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
