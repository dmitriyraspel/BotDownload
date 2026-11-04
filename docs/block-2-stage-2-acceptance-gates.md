# Block 2 / Stage 2 — remaining acceptance gates

**Normative v1 policy:** [SECURITY_POLICY_V1.md](SECURITY_POLICY_V1.md)
(approved 2026-11-03) overrides earlier network/isolation scope. In v1
block only IPv4 `127/8` and IPv6 `::1/128` for yt-dlp and children;
other private and Fake-IP destinations are intentionally not blocked.

This branch contains experimental namespace and egress modules. **They are not
production enabled and Stage 2 is not complete.** In particular, do not
connect `run_media_dispatcher` to the production SQLite queue until acceptance.
The current experimental dispatcher attempts real execution and stages a
validated result; failures still mark tasks failed.

## What can be tested offline

```bash
.venv/bin/python -m pytest -q tests/test_media_namespace_bridge.py tests/test_media_namespace_runner.py tests/test_media_egress_gateway.py tests/test_media_egress_socket.py
```

## Required before enabling media IPC

1. Enforce a **filesystem and Unix-socket boundary** in addition to network
   namespaces. An unprivileged network namespace does not hide the host
   filesystem or host Unix sockets. A worker must not reach arbitrary host
   services via their Unix sockets.
2. Use the approved **single unprivileged service UID** in v1. A distinct
   worker/gateway Unix account is deferred to v2. Verify gateway Unix-socket
   ownership, limited scope and that the worker cannot bypass the mandatory
   v1 loopback restriction. One UID does not isolate bot secrets.
3. Verify that all yt-dlp extractor, media, and redirect requests are proxied.
   Reject requests to unexpected domains; add a safe, explicit domain policy
   for required YouTube dependencies. Verify actual IPv4 `127/8` and IPv6
   `::1` rejection under DNS, redirects and yt-dlp internal requests, with
   ordinary/Fake-IP system DNS still functional. Other internal addresses
   are not blocked under v1.
4. Apply cumulative bytes, process-tree, CPU, memory and disk quotas, including
   child processes, partial fragments and intermediate files. Current
   `--max-filesize` is not a cumulative quota.
5. Experimental worker IPC `execute_media` and lease verification exist.
   Validate cancellation, deadline expiry/renewal, bounded results and
   fail-closed behavior under worker interruption. Keep SQLite writes in the
   trusted broker.
6. Stage the resulting regular file atomically in a bot-owned private
   directory and publish via a compare-and-swap status transition. Ensure
   cancellation and crashes cannot publish stale files.
7. Perform a real YouTube download on Debian 12 under `tgbot` through the
   configured gateway; record sanitized logs; verify blocked loopback and
   no host-network fallback. The explicit smoke command is
   `python -m bot.media_integration_smoke --url URL --download-dir PATH`.
   A green offline test suite does not prove live network isolation.
8. Test restart, kill -9, timeout, cancellation, disk full, malformed output,
   and gateway outage before production enablement.

The code must not claim successful real-network validation until the Debian
host has actually run that test.

## Debian 12 test evidence — 2026-11-04 (operator reported)

The operator ran the following on the Debian 12 test host. These results are
recorded as **operator-reported evidence**, not independently reproduced by
GitHub CI or this repository review.

- Live opt-in media smoke, as unprivileged `tgbot`, using
  `https://www.youtube.com/watch?v=jNQXAC9IVRw`: **PASS**;
  task status `upload_pending`; output `jNQXAC9IVRw.webm`, **474494 bytes**.
  This confirms a positive media path on the host with its existing DNS/Fake-IP
  configuration; it is not a full security acceptance test.
- `python -m pytest -q tests/test_media_egress_gateway.py`:
  **32 passed in 0.08s**.
- Combined offline regression suite covering egress gateway/socket,
  namespace bridge/runner, media IPC/queue, cancellation, crash recovery,
  startup recovery and stage-4 integration: **58 passed in 1.20s**.
- A separate Unix-socket CONNECT probe run as `tgbot` against
  `bot.media_egress_gateway.handle_connect`: **3/3 denied** with HTTP 403
  for `127.0.0.1`, `127.255.255.254`, and `[::1]`.
  Gateway warnings `EgressDenied: Destination not permitted` are expected.

**Evidence limits:** the CONNECT probe is a gateway request-validation test:
these literal IP destinations are also rejected by the gateway's domain
allowlist, so this alone does **not** establish that DNS-resolved loopback IPs
are blocked or that yt-dlp/its children cannot bypass the gateway. Offline
cancellation/recovery tests do not establish live process-tree termination.

**Additional operator-reported DNS-filter test (2026-11-04): PASS 3/3.**
With `asyncio` event-loop `getaddrinfo` patched to return only a loopback
answer for allowed host `www.youtube.com`, `resolve_public()` raised
`EgressDenied` for `127.0.0.1`, `127.255.255.254` and `::1`.
This confirms the gateway's DNS-answer filtering logic, **not** live
network-namespace enforcement or bypass resistance.

**Additional operator-reported namespace route test (2026-11-04): PASS 2/2.**
As `tgbot`, `unshare --user --map-root-user --net --fork` started a fresh
network namespace. Direct TCP attempts to `1.1.1.1:443` and
`198.18.0.44:443` both failed with `OSError: [Errno 101] Network is
unreachable`. This demonstrates no direct IPv4 route in that freshly
created namespace, **not** a complete no-bypass proof for the actual
media child-process tree or host Unix sockets. Fake-IP remains permitted
through the v1 gateway.

**Additional operator-reported child-process IPv4/IPv6 route test (2026-11-04): PASS 2/2.**
An unprivileged `tgbot` network namespace launched a child Python process.
Direct TCP to `1.1.1.1:443` failed with `Errno 101 Network is unreachable`;
direct TCP to `[2606:4700:4700::1111]:443` failed with
`Errno 99 Cannot assign requested address`. Both attempts were denied.
This demonstrates no direct IPv4/IPv6 access for that test child, but does
not prove actual yt-dlp/FFmpeg process-tree isolation or host Unix-socket
confinement.

**Additional operator-reported OS process-group timeout probe (2026-11-04): PASS.**
As `tgbot`, a Python subprocess started in a new session was timed out after
0.5 seconds, its process group was sent `SIGKILL`, and the parent awaited
termination with exit code `-SIGKILL`. This tests the OS-level mechanism,
not cancellation or cleanup of an actual media worker/process tree.

**Additional operator-reported parent/child process-group kill probe (2026-11-04): PASS.**
A test parent launched a sleeping child in the same process group under
`tgbot`; `SIGKILL` sent to the process group terminated the parent and the
child (child absent or zombie in `/proc`). This is OS process-group evidence,
not proof of the actual media worker cancellation/cleanup path.

**Still open before Stage 2 acceptance:** prove DNS-resolved IPv4/IPv6 loopback denial on the **live media path**
(beyond the mocked resolver test); prove no direct-network/Unix-socket bypass
from the namespace (including child processes); exercise live timeout,
cancellation, kill -9, gateway outage, cleanup and cumulative resource limits.
The full Telegram metadata → choice → download → delivery path remains
unverified and production media dispatch remains disabled.
