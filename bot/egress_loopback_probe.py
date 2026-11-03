"""Live, opt-in loopback egress test with a controlled local TCP listener.

A baseline connection must succeed before a blocked sandbox connection can
count as evidence. No privileged network configuration is changed.
"""
import socket
import subprocess
import sys
import threading

from .network_egress import systemd_metadata_guard


def _connect(port: int, *, ipv6: bool = False) -> int:
    try:
        with socket.create_connection(("::1" if ipv6 else "127.0.0.1", port), timeout=2):
            print("CONNECTED", flush=True)
            return 0
    except OSError as exc:
        print(f"BLOCKED_OR_FAILED:{type(exc).__name__}", flush=True)
        return 1


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--child-port", type=int)
    parser.add_argument("--ipv6", action="store_true")
    args = parser.parse_args(argv)
    if args.child_port is not None:
        return _connect(args.child_port, ipv6=args.ipv6)
    family = socket.AF_INET6 if args.ipv6 else socket.AF_INET
    address = "::1" if args.ipv6 else "127.0.0.1"
    with socket.socket(family, socket.SOCK_STREAM) as server:
        try:
            server.bind((address, 0))
        except OSError as exc:
            print(f"INCONCLUSIVE: listener unavailable: {exc}")
            return 2
        server.listen(4)
        server.settimeout(8)
        port = server.getsockname()[1]
        stop = threading.Event()

        def accept_connections():
            while not stop.is_set():
                try:
                    connection, _ = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    return
                connection.close()

        server.settimeout(0.2)
        thread = threading.Thread(target=accept_connections, daemon=True)
        thread.start()
        child = [sys.executable, "-m", "bot.egress_loopback_probe", "--child-port", str(port)]
        if args.ipv6:
            child.append("--ipv6")
        try:
            guarded_command = systemd_metadata_guard(child)
            # Compare identical systemd services, changing only IPAddressDeny.
            # This rules out unrelated sandbox restrictions and user permissions.
            baseline_command = [arg for arg in guarded_command
                                if not arg.startswith("--property=IPAddressDeny=")]
            baseline = subprocess.run(baseline_command, capture_output=True,
                                      text=True, timeout=15)
            print(f"Baseline: {baseline.stdout.strip()} (exit={baseline.returncode})")
            if baseline.returncode != 0 or baseline.stdout.strip() != "CONNECTED":
                print("INCONCLUSIVE: same-user systemd baseline failed")
                if baseline.stderr.strip():
                    print(baseline.stderr.strip()[:500], file=sys.stderr)
                return 2
            guarded = subprocess.run(guarded_command,
                                     capture_output=True, text=True, timeout=15)
            print(f"Confined: {guarded.stdout.strip()} (exit={guarded.returncode})")
            if guarded.stderr.strip():
                print(guarded.stderr.strip()[:500], file=sys.stderr)
            if guarded.returncode == 0 or guarded.stdout.strip() == "CONNECTED":
                print("FAIL: sandbox connected to local listener")
                return 1
            if guarded.stdout.strip().startswith("BLOCKED_OR_FAILED:"):
                print("PASS: sandbox could not connect to reachable loopback listener")
                return 0
            print("INCONCLUSIVE: sandbox command did not execute probe")
            return 2
        finally:
            stop.set()
            thread.join(timeout=1)


if __name__ == "__main__":
    raise SystemExit(main())
