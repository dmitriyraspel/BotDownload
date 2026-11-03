"""Restricted FFmpeg invocation for already-downloaded local media only."""
import asyncio
from pathlib import Path


class MediaProcessingError(Exception):
    pass


def validate_local_media_file(path: Path, workdir: Path) -> Path:
    root = workdir.resolve(strict=True)
    if path.is_symlink():
        raise MediaProcessingError("Символические ссылки запрещены")
    candidate = path.resolve(strict=True)
    if not candidate.is_file() or root not in candidate.parents:
        raise MediaProcessingError("Входной файл вне рабочей папки")
    return candidate


async def run_ffmpeg(*, executable: Path, input_file: Path, output_file: Path,
                     workdir: Path, mp3: bool, timeout: int) -> None:
    """No shell, no network protocols, no arbitrary user-supplied arguments."""
    if timeout <= 0:
        raise MediaProcessingError("Некорректный таймаут")
    source = validate_local_media_file(input_file, workdir)
    root = workdir.resolve(strict=True)
    output = output_file.resolve(strict=False)
    if output_file.is_symlink() or root not in output.parents or output.exists() or output.suffix.lower() != (".mp3" if mp3 else ".mp4"):
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
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        output.unlink(missing_ok=True)
        raise MediaProcessingError("Превышено время обработки FFmpeg") from exc
    if process.returncode != 0:
        output.unlink(missing_ok=True)
        raise MediaProcessingError("Ошибка обработки FFmpeg")
