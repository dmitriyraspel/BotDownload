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

**Still open before Stage 2 acceptance:** prove DNS-resolved IPv4/IPv6 loopback
denial on the actual media path; prove no direct-network/Unix-socket bypass
from the namespace (including child processes); exercise live timeout,
cancellation, kill -9, gateway outage, cleanup and cumulative resource limits.
The full Telegram metadata → choice → download → delivery path remains
unverified and production media dispatch remains disabled.
