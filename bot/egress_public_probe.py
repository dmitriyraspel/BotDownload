"""Opt-in HTTPS reachability check inside the same systemd sandbox.

Run as root on the deployment host. The baseline and confined process use
identical settings except IPAddressDeny. This is a diagnostic, not an SSRF proof.
"""
import argparse
import subprocess
import sys
import urllib.error
import urllib.request

from .network_egress import systemd_metadata_guard

URL = "https://example.com/"


def fetch_public_https() -> int:
    try:
        request = urllib.request.Request(URL, headers={"User-Agent": "BotDownload-egress-probe/1"})
        with urllib.request.urlopen(request, timeout=8) as response:
            response.read(1)
            if response.status != 200:
                print(f"HTTP_STATUS:{response.status}", flush=True)
                return 2
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        print(f"UNREACHABLE:{type(exc).__name__}", flush=True)
        return 2
    print("HTTPS_OK", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args(argv)
    if args.child:
        return fetch_public_https()
    child = [sys.executable, "-m", "bot.egress_public_probe", "--child"]
    guarded = systemd_metadata_guard(child)
    baseline = [part for part in guarded if not part.startswith("--property=IPAddressDeny=")]
    for label, command in (("Baseline", baseline), ("Confined", guarded)):
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=25)
        except subprocess.TimeoutExpired:
            print(f"{label}: INCONCLUSIVE: subprocess timeout")
            return 2
        print(f"{label}: {result.stdout.strip() or 'NO OUTPUT'} (exit={result.returncode})")
        if result.stderr.strip():
            print(result.stderr.strip()[:500], file=sys.stderr)
        if result.returncode != 0 or result.stdout.strip() != "HTTPS_OK":
            print("INCONCLUSIVE: public HTTPS connectivity not established")
            return 2
    print("PASS: public HTTPS reachable with IPAddressDeny enabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
