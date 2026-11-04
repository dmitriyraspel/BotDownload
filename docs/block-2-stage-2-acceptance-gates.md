# Block 2 / Stage 2 — remaining acceptance gates

This branch contains experimental namespace and egress modules. **They are not
production enabled and Stage 2 is not complete.** In particular, do not
connect `run_media_dispatcher` to the production SQLite queue: it intentionally
marks jobs failed.

## What can be tested offline

```bash
.venv/bin/python -m pytest -q tests/test_media_namespace_bridge.py tests/test_media_namespace_runner.py tests/test_media_egress_gateway.py tests/test_media_egress_socket.py
```

## Required before enabling media IPC

1. Enforce a **filesystem and Unix-socket boundary** in addition to network
   namespaces. An unprivileged network namespace does not hide the host
   filesystem or host Unix sockets. A worker must not reach arbitrary host
   services via their Unix sockets.
2. Run gateway under a distinct account or other meaningful trust boundary,
   with strict ownership and permissions. The current Unix gateway is an
   experimental primitive, not a complete security perimeter.
3. Verify that all yt-dlp extractor, media, and redirect requests are proxied.
   Reject requests to unexpected domains; add a safe, explicit domain policy
   for required YouTube dependencies, and test DNS rebinding.
4. Apply cumulative bytes, process-tree, CPU, memory and disk quotas, including
   child processes, partial fragments and intermediate files. Current
   `--max-filesize` is not a cumulative quota.
5. Add worker IPC execution with lease verification, active cancellation,
   deadline renewal, and a bounded, validated result protocol. Keep the worker
   read-only with respect to SQLite.
6. Stage the resulting regular file atomically in a bot-owned private
   directory and publish via a compare-and-swap status transition. Ensure
   cancellation and crashes cannot publish stale files.
7. Perform a real YouTube download on Debian 12 under `tgbot` through the
   configured gateway; record the sanitized logs and verify no host-network
   fallback. No remote server access is available from the GitHub connector.
8. Test restart, kill -9, timeout, cancellation, disk full, malformed output,
   and gateway outage before production enablement.

The code must not claim successful real-network validation until the Debian
host has actually run that test.
