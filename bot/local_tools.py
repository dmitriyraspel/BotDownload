"""Discover optional project-local executables without changing global PATH."""
from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def deno_path() -> str | None:
    executable = "deno.exe" if os.name == "nt" else "deno"
    candidate = PROJECT_ROOT / "tools" / "deno" / executable
    return str(candidate) if candidate.is_file() else None


def yt_dlp_js_options() -> dict:
    path = deno_path()
    return {"js_runtimes": {"deno": {"path": path}}} if path else {}
