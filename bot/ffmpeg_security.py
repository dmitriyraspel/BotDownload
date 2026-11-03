"""Restricted FFmpeg invocation for already-downloaded local media only."""
import asyncio
import os
from pathlib import Path
import signal


class MediaProcessingError(Exception):
    pass


ALLOWED_INPUT_SUFFIXES = frozenset({".mp4", ".m4a", ".webm", ".mkv", ".mov", ".mp3", ".opus", ".ogg"})


def validate_local_media_file(path: Path, workdir: Path) -> Path:
    root = workdir.resolve(strict=True)
    if path.is_symlink():
        raise MediaProcessingError("Символические ссылки запрещены")
    candidate = path.resolve(strict=True)
    if (not candidate.is_file() or root not in candidate.parents
            or candidate.suffix.lower() not in ALLOWED_INPUT_SUFFIXES):
        raise MediaProcessingError("Недопустимый локальный медиафайл")
    return candidate


def _stop_process(process) -> None:
    """Kill FFmpeg and its children on POSIX, without touching other processes."""
    if process.returncode is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()


async def run_ffmpeg(*, executable: Path, input_file: Path, output_file: Path,
                     workdir: Path, mp3: bool, timeout: int,
                     max_output_bytes: int = 2_000_000_000) -> None:
    """Fixed local-only conversion with deadline and bounded output size.

    OS-level CPU/RAM limits and network isolation are still required for
    hostile media; this function alone is not a complete sandbox.
    """
    if timeout <= 0 or max_output_bytes <= 0:
        raise MediaProcessingError("Некорректные ограничения обработки")
    source = validate_local_media_file(input_file, workdir)
    root = workdir.resolve(strict=True)
    output = output_file.resolve(strict=False)
    if (output_file.is_symlink() or root not in output.parents or output.exists()
            or output.suffix.lower() != (".mp3" if mp3 else ".mp4")):
        raise MediaProcessingError("Недопустимый выходной файл")
    if not executable.resolve(strict=True).is_file():
        raise MediaProcessingError("FFmpeg не найден")
    args = [
        str(executable), "-nostdin", "-hide_banner", "-loglevel", "error",
        "-n", "-protocol_whitelist", "file,pipe", "-i", str(source),
        "-map_metadata", "-1",
    ]
    if mp3:
        args += ["-vn", "-c:a", "libmp3lame", "-q:a", "0"]
    else:
        args += ["-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart"]
    args.append(str(output))
    process = await asyncio.create_subprocess_exec(
        *args, cwd=str(root), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=(os.name == "posix"),
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while process.returncode is None:
            if output.exists() and output.stat().st_size > max_output_bytes:
                raise MediaProcessingError("Превышен лимит размера файла FFmpeg")
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise MediaProcessingError("Превышено время обработки FFmpeg")
            try:
                await asyncio.wait_for(process.wait(), timeout=min(0.25, remaining))
            except asyncio.TimeoutError:
                continue
        if process.returncode != 0:
            raise MediaProcessingError("Ошибка обработки FFmpeg")
        if not output.is_file() or output.stat().st_size > max_output_bytes:
            raise MediaProcessingError("Некорректный размер результата FFmpeg")
    except BaseException:
        _stop_process(process)
        await asyncio.shield(process.wait())
        output.unlink(missing_ok=True)
        raise
