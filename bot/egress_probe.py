"""Live, opt-in probe for systemd IPAddressDeny enforcement.

Run manually as root on the target host. No configuration changes are made.
The probe only attempts TCP connections; it never sends application data.
"""
import argparse
import socket
import subprocess
import sys

from .network_egress import systemd_metadata_guard

TARGETS = ("127.0.0.1", "10.255.255.1", "169.254.169.254", "::1")


def probe_target(address: str, port: int) -> int:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)
            sock.connect((address, port))
    except PermissionError:
        print("DENIED", flush=True)
        return 0
    except OSError as exc:
        print(f"INCONCLUSIVE:{type(exc).__name__}:{exc.errno}", flush=True)
        return 2
    print("CONNECTED", flush=True)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe systemd egress enforcement")
    parser.add_argument("--child-address", choices=TARGETS)
    parser.add_argument("--port", type=int, default=443)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.child_address:
        return probe_target(args.child_address, args.port)

    print("Live egress probe: DENIED=blocked, CONNECTED=unsafe, INCONCLUSIVE=not proven.")
    failures = 0
    for address in TARGETS:
        command = systemd_metadata_guard([
            sys.executable, "-m", "bot.egress_probe",
            "--child-address", address, "--port", str(args.port),
        ])
        result = subprocess.run(command, capture_output=True, text=True, timeout=20,
                                check=False)
        status = result.stdout.strip()
        print(f"{address}: {status or 'NO OUTPUT'} (exit={result.returncode})")
        if result.returncode != 0 or status != "DENIED":
            failures += 1
            if result.stderr.strip():
                print(result.stderr.strip()[:500], file=sys.stderr)
    if failures:
        print("FAIL: isolation not demonstrated for all targets")
        return 1
    print("PASS: selected targets denied (not a complete security proof)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
