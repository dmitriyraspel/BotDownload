"""Install a pinned Deno binary into this repository's ignored tools/ folder.

Run with the project's Python interpreter; no global installation or PATH changes.
"""
from pathlib import Path
import platform
import shutil
import sys
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile

VERSION = "2.5.6"
ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "tools" / "deno"


def main() -> None:
    system = platform.system()
    machine = platform.machine().lower()
    if machine not in ("amd64", "x86_64", "arm64", "aarch64"):
        raise SystemExit(f"Unsupported CPU architecture: {machine}")
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    if system == "Windows":
        if arch != "x86_64":
            raise SystemExit("This installer currently supports Windows x86_64 only")
        target, binary = "x86_64-pc-windows-msvc", "deno.exe"
    elif system == "Linux":
        target, binary = f"{arch}-unknown-linux-gnu", "deno"
    else:
        raise SystemExit(f"Unsupported OS: {system}")

    url = f"https://github.com/denoland/deno/releases/download/v{VERSION}/deno-{target}.zip"
    DEST.mkdir(parents=True, exist_ok=True)
    print(f"Downloading Deno {VERSION} for {target} from official GitHub releases...")
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / "deno.zip"
        with urlopen(url, timeout=60) as response, archive.open("wb") as output:
            if response.status != 200:
                raise RuntimeError(f"Download failed: HTTP {response.status}")
            shutil.copyfileobj(response, output)
        with ZipFile(archive) as zipped:
            if binary not in zipped.namelist():
                raise RuntimeError(f"Missing {binary} in downloaded archive")
            staged = Path(temporary) / binary
            with zipped.open(binary) as source, staged.open("wb") as output:
                shutil.copyfileobj(source, output)
        destination = DEST / binary
        shutil.move(str(staged), str(destination))
        if system != "Windows":
            destination.chmod(0o755)
    print(f"Installed: {destination}")
    print("Deno is local to the project; no system PATH changes were made.")


if __name__ == "__main__":
    main()
