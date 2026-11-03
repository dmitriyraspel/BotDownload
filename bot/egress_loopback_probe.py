"""Live, opt-in loopback egress test with a controlled local TCP listener.

A baseline connection must succeed before a blocked sandbox connection can
count as evidence. No privileged network configuration is changed.
"""
import socket
import subprocess
import sys
import threading

from .network_egress import systemd_metadata_guard


def _connect(port: int) -> int:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            print("CONNECTED", flush=True)
            return 0
    except OSError as exc:
        print(f"BLOCKED_OR_FAILED:{type(exc).__name__}", flush=True)
        return 1


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--child-port", type=int)
    args = parser.parse_args(argv)
    if args.child_port is not None:
        return _connect(args.child_port)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(4)
        server.settimeout(8)
        port = server.getsockname()[1]
        accepted = []
        stop = threading.Event()

        def accept_connections():
            while not stop.is_set():
                try:
                    connection, _ = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    return
                accepted.append(True)
                connection.close()

        server.settimeout(0.2)
        thread = threading.Thread(target=accept_connections, daemon=True)
        thread.start()
        child = [sys.executable, "-m", "bot.egress_loopback_probe", "--child-port", str(port)]
        try:
            baseline = subprocess.run(child, capture_output=True, text=True, timeout=8)
            print(f"Baseline: {baseline.stdout.strip()} (exit={baseline.returncode})")
            if baseline.returncode != 0 or baseline.stdout.strip() != "CONNECTED":
                print("INCONCLUSIVE: baseline loopback connection failed")
                return 2
            guarded = subprocess.run(systemd_metadata_guard(child),
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
