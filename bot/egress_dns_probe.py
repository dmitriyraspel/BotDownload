"""Diagnose DNS versus public TCP access in the systemd sandbox.

Opt-in operator diagnostic; does not modify host configuration.
"""
import argparse
import socket
import subprocess
import sys

from .network_egress import systemd_metadata_guard

HOST = "example.com"


def diagnose() -> int:
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(
            HOST, 443, type=socket.SOCK_STREAM)})
        print("DNS_OK:" + ",".join(addresses), flush=True)
    except OSError as exc:
        print(f"DNS_FAIL:{type(exc).__name__}:{exc}", flush=True)
        return 2
    for address in addresses:
        try:
            with socket.create_connection((address, 443), timeout=4):
                print(f"TCP_OK:{address}", flush=True)
                return 0
        except OSError as exc:
            print(f"TCP_FAIL:{address}:{type(exc).__name__}", flush=True)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args(argv)
    if args.child:
        return diagnose()
    child = [sys.executable, "-m", "bot.egress_dns_probe", "--child"]
    guarded = systemd_metadata_guard(child)
    baseline = [arg for arg in guarded if not arg.startswith("--property=IPAddressDeny=")]
    for name, command in (("Baseline", baseline), ("Confined", guarded)):
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=25)
        except subprocess.TimeoutExpired:
            print(f"{name}: subprocess timeout")
            return 2
        print(f"{name} (exit={result.returncode}):")
        print(result.stdout.strip() or "NO OUTPUT")
        if result.stderr.strip():
            print(result.stderr.strip()[:500], file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
