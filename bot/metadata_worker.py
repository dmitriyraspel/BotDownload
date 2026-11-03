"""Child-process entry point for metadata extraction.

This process must run behind enforced network egress policy before Telegram
is switched to it. Stdout is reserved for one JSON object.
"""
import json
import sys

from .metadata import _extract
from .telegram_handlers import ALLOWED_HOSTS, validate_media_url
from .network_security import validate_public_https_target


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not validate_media_url(args[0]):
        return 2
    try:
        # Repeat preflight inside the confined worker; the parent check alone
        # cannot protect against DNS changes between validation and extraction.
        validate_public_https_target(args[0], allowed_hosts=ALLOWED_HOSTS)
        result = _extract(args[0])
        payload = json.dumps(result, ensure_ascii=False, allow_nan=False)
        if len(payload.encode("utf-8")) > 262144:
            return 3
        sys.stdout.write(payload)
        sys.stdout.flush()
        return 0
    except Exception:
        # Do not leak URL tokens, yt-dlp diagnostics, or internal paths.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
