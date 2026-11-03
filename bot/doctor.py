"""Portable, read-only deployment readiness checks.

Run with `python -m bot.doctor`. Does not need root, network access or
knowledge of a particular server's resolver or firewall.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys


def inspect_environment(*, python_version=None, which=None, module_available=None,
                        project_root=None) -> dict:
    version = python_version or sys.version_info
    find = which or shutil.which
    module_exists = module_available or (lambda name: importlib.util.find_spec(name) is not None)
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parent.parent
    checks = []
    def add(name, ok, detail, required=True):
        checks.append({"name": name, "ok": bool(ok), "required": required, "detail": detail})

    add("python", tuple(version[:2]) >= (3, 11),
        f"Python {version[0]}.{version[1]}; требуется 3.11+")
    for binary in ("ffmpeg", "ffprobe"):
        found = find(binary)
        add(binary, bool(found), found or f"{binary} не найден в PATH")
    for module in ("aiogram", "yt_dlp", "yaml"):
        try:
            found = module_exists(module)
        except (ImportError, ValueError):
            found = False
        add(module, found, "доступен" if found else "Python-модуль не установлен")
    add("env", (root / ".env").is_file(),
        "локальный .env найден" if (root / ".env").is_file() else
        "создайте .env из env.example и заполните секреты")
    add("config", (root / "config.yaml").is_file(),
        "config.yaml найден" if (root / "config.yaml").is_file() else
        "создайте config.yaml из шаблона")
    add("linux", sys.platform.startswith("linux"),
        "Linux" if sys.platform.startswith("linux") else
        "для production рекомендуется Linux", required=False)
    return {"ready": all(item["ok"] for item in checks if item["required"]),
            "checks": checks}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only BotDownload deployment checks")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    args = parser.parse_args(argv)
    report = inspect_environment()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for item in report["checks"]:
            state = "OK" if item["ok"] else ("WARN" if not item["required"] else "FAIL")
            print(f"[{state}] {item['name']}: {item['detail']}")
        print("READY" if report["ready"] else "NOT READY")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
