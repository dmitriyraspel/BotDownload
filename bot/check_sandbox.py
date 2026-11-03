"""Run the offline sandbox readiness check as the service user.

Usage: python -m bot.check_sandbox /absolute/private/workspace
"""
import asyncio
from pathlib import Path
import sys

from .network_isolation import SandboxUnavailable
from .sandbox_probe import verify_no_network_sandbox


def main() -> int:
    if len(sys.argv) != 2:
        print("Использование: python -m bot.check_sandbox /абсолютный/каталог", file=sys.stderr)
        return 2
    try:
        asyncio.run(verify_no_network_sandbox(Path(sys.argv[1])))
    except (SandboxUnavailable, OSError) as exc:
        print(f"Проверка изоляции не пройдена: {exc}", file=sys.stderr)
        return 1
    print("Bubblewrap: запуск в отдельном сетевом пространстве успешен")
    print("Это не проверка защиты от SSRF и не разрешение включать скачивание.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
