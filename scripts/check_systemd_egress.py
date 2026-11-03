#!/usr/bin/env python3
"""Portable, read-only systemd IP policy diagnostic.

Run as root on the target Linux host. No bot config or firewall is changed.
Uses temporary transient services; never treats a failed connection alone as
proof of filtering. This is a diagnostic, NOT authorization to enable downloads.
"""
import argparse
import ipaddress
import os
import socket
import subprocess
import sys
import threading
from contextlib import closing

DENIED = (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24",
    "192.0.2.0/24", "192.168.0.0/16", "198.18.0.0/15",
    "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4",
    "240.0.0.0/4", "::/128", "::1/128", "::ffff:0:0/96",
    "64:ff9b:1::/48", "100::/64", "2001:db8::/32",
    "fc00::/7", "fe80::/10", "ff00::/8",
)
PROBE = """import socket,sys
host,port,family=sys.argv[1],int(sys.argv[2]),int(sys.argv[3])
s=socket.socket(family,socket.SOCK_STREAM)
s.settimeout(2)
try:
 s.connect((host,port))
except OSError as exc:
 print('FAILED:',repr(exc))
 sys.exit(10)
else:
 print('CONNECTED')
finally:
 s.close()
"""


def run_probe(address, port, family, policy):
    args = ["systemd-run", "--system", "--quiet", "--wait", "--collect",
            "--pipe", "--property=Type=exec",
            "--property=RuntimeMaxSec=10",
            "--property=RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6"]
    if policy:
        args += ["--property=IPAddressDeny=" + " ".join(DENIED)]
    args += ["--", sys.executable, "-I", "-c", PROBE,
             address, str(port), str(family)]
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"systemd-run failed: {exc}") from exc


def local_pair(family, address):
    with closing(socket.socket(family, socket.SOCK_STREAM)) as server:
        server.bind((address, 0))
        server.listen(4)
        server.settimeout(10)
        port = server.getsockname()[1]
        results = []
        def accept():
            try:
                for _ in range(2):
                    with closing(server.accept()[0]):
                        pass
            except socket.timeout:
                pass
        thread = threading.Thread(target=accept, daemon=True)
        thread.start()
        for policy in (False, True):
            results.append(run_probe(address, port, family, policy))
        return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-host", default="www.youtube.com",
                        help="public hostname for DNS and HTTPS checks")
    args = parser.parse_args()
    if os.geteuid() != 0 or not os.path.isdir("/run/systemd/system"):
        parser.error("requires root and systemd")
    try:
        infos = socket.getaddrinfo(args.public_host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        print(f"INCONCLUSIVE: host DNS lookup failed: {exc}")
        return 2
    public = []
    for family, _, _, _, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_global and family in (socket.AF_INET, socket.AF_INET6):
            public.append((family, sockaddr[0]))
    if not public:
        print("INCONCLUSIVE: DNS returned no global addresses")
        return 2
    passed = True
    for family, addr in ((socket.AF_INET, "127.0.0.1"),
                         (socket.AF_INET6, "::1")):
        try:
            baseline, restricted = local_pair(family, addr)
        except OSError as exc:
            print(f"INCONCLUSIVE {addr}: local listener unavailable: {exc}")
            passed = False
            continue
        good = baseline.returncode == 0 and restricted.returncode != 0
        print(f"{addr}: baseline={baseline.returncode} restricted={restricted.returncode} "
              f"{'PASS' if good else 'FAIL/INCONCLUSIVE'}")
        if not good:
            print("  baseline:", baseline.stdout.strip(), baseline.stderr.strip()[-250:])
            print("  restricted:", restricted.stdout.strip(), restricted.stderr.strip()[-250:])
            passed = False
    # Check that real public HTTPS remains reachable under the selective policy.
    # A successful TCP connection does not establish TLS correctness.
    for family, addr in dict.fromkeys(public):
        baseline = run_probe(addr, 443, family, False)
        restricted = run_probe(addr, 443, family, True)
        good = baseline.returncode == 0 and restricted.returncode == 0
        print(f"public {addr}: baseline={baseline.returncode} "
              f"restricted={restricted.returncode} "
              f"{'PASS' if good else 'FAIL/INCONCLUSIVE'}")
        if not good:
            print("  baseline:", baseline.stdout.strip(), baseline.stderr.strip()[-250:])
            print("  restricted:", restricted.stdout.strip(), restricted.stderr.strip()[-250:])
            passed = False
    print("DIAGNOSTIC PASS" if passed else "DIAGNOSTIC INCONCLUSIVE/FAIL")
    print("This does NOT verify DNS inside worker, rebinding, all denied ranges, "
          "or production worker confinement. Downloads must remain disabled.")
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
