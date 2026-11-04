"""Opt-in real namespace resource-limit probe; no Telegram or production DB.

Tests wall-clock timeout and a one-byte output cap using the same isolated
runner as the real media worker. Each case uses a fresh private workspace.
"""
import argparse
import asyncio
import os
from pathlib import Path
import tempfile

from .media_egress_gateway import handle_connect
from .media_executor import validate_media_url
from .media_isolated_runner import execute_isolated


async def run(url: str, *, timeout_seconds: int = 1) -> int:
    validate_media_url(url)
    if os.name != "posix" or os.geteuid() == 0:
        raise RuntimeError("Run as unprivileged Linux user")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 10:
        raise ValueError("timeout_seconds must be 1..10")
    with tempfile.TemporaryDirectory(prefix="botdownload-resource-") as temp:
        root = Path(temp)
        gateway = root / "gateway.sock"
        server = await asyncio.start_unix_server(handle_connect, path=str(gateway))
        os.chmod(gateway, 0o600)
        try:
            for label, seconds, max_bytes in (
                ("timeout", timeout_seconds, 256 * 1024 * 1024),
                ("size", 120, 1),
            ):
                workspace = root / label
                workspace.mkdir(mode=0o700)
                try:
                    async with server:
                        result = await execute_isolated(
                            url, gateway=gateway, workspace=workspace,
                            timeout_seconds=seconds, max_bytes=max_bytes,
                        )
                    print("FAIL:", label, "accepted output:", result)
                    return 1
                except (TimeoutError, RuntimeError) as exc:
                    # An early extractor/network failure is not proof of a
                    # resource limit. The timeout case must time out; the
                    # size case must explicitly report oversized output.
                    message = str(exc)
                    if label == "timeout" and isinstance(exc, TimeoutError):
                        print("PASS: wall-clock timeout enforced")
                    elif label == "size" and "Размер файла вне допустимого диапазона" in message:
                        print("PASS: one-byte output cap enforced")
                    else:
                        print("INCONCLUSIVE:", label, type(exc).__name__, message)
                        return 2
                finally:
                    # The isolated runner owns process-group termination.
                    # Its task-local diagnostic may remain on errors.
                    leftovers = [p.name for p in workspace.iterdir()
                                 if p.name != ".namespace-stderr.log"]
                    if leftovers:
                        print("FAIL: partial output remains:", leftovers)
                        return 1
                    for file in workspace.iterdir():
                        file.unlink()
                # An async context closes its server; create a new one for
                # the next case on the same private gateway path.
                if label == "timeout":
                    gateway.unlink(missing_ok=True)
                    server = await asyncio.start_unix_server(
                        handle_connect, path=str(gateway))
                    os.chmod(gateway, 0o600)
            print("PASS: real isolated runner resource limits")
            return 0
        finally:
            server.close()
            await server.wait_closed()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=1)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.url, timeout_seconds=args.timeout_seconds)))


if __name__ == "__main__":
    main()
