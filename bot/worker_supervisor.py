"""Supervise the offline IPC worker under the same unprivileged V1 UID."""
import asyncio
import os
from pathlib import Path
import signal
import sys
import tempfile

from .worker_ipc import ping


class OfflineWorkerSupervisor:
    def __init__(self, db_path: Path):
        self.db_path = db_path.resolve()
        self.process: asyncio.subprocess.Process | None = None
        self._runtime: tempfile.TemporaryDirectory | None = None
        self.socket_path: Path | None = None

    async def start(self) -> Path:
        if self.process is not None:
            raise RuntimeError("Worker уже запущен")
        if os.name != "posix" or os.geteuid() == 0:
            raise RuntimeError("Worker требует непривилегированного Linux-пользователя")
        self._runtime = tempfile.TemporaryDirectory(prefix="botdownload-ipc-")
        os.chmod(self._runtime.name, 0o700)
        self.socket_path = Path(self._runtime.name) / "worker.sock"
        env = dict(os.environ)
        env.update(
            BOTDOWNLOAD_CLIENT_USER=__import__("pwd").getpwuid(os.geteuid()).pw_name,
            BOTDOWNLOAD_WORKER_DB=str(self.db_path),
            BOTDOWNLOAD_WORKER_SOCKET=str(self.socket_path),
        )
        try:
            self.process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "bot.worker_service", env=env,
                start_new_session=True,
            )
            for _ in range(50):
                if self.process.returncode is not None:
                    raise RuntimeError("Worker завершился при запуске")
                if await ping(self.socket_path, timeout=0.15):
                    return self.socket_path
                await asyncio.sleep(0.1)
            raise RuntimeError("Worker не ответил на IPC ping")
        except BaseException:
            await self.stop()
            raise

    async def wait(self) -> int:
        if self.process is None:
            raise RuntimeError("Worker не запущен")
        return await self.process.wait()

    async def stop(self) -> None:
        process = self.process
        self.process = None
        if process is not None:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await process.wait()
            else:
                await process.wait()
        if self._runtime is not None:
            self._runtime.cleanup()
            self._runtime = None
        self.socket_path = None
