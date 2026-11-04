# Dedicated worker IPC: experimental, production downloads disabled

**Document priority:** [SECURITY_POLICY_V1.md](SECURITY_POLICY_V1.md)
(approved 2026-11-03) overrides this historical implementation log wherever
requirements differ. In v1 all service processes use **one unprivileged UID**;
network blocking for yt-dlp and children covers only `127.0.0.0/8` and
`::1/128`, not RFC1918, link-local, metadata or Fake-IP ranges.


The independent offline worker is implemented in `bot.worker_service`.
It exposes versioned Unix-socket operations for ping, read-only task
status, lease reservation/cancellation, the fixed offline fixture
(`execute_offline`) and an **experimental** lease-authorized media execution
operation (`execute_media`). The media path runs only through the explicitly
invoked test dispatcher; production Telegram downloads remain disabled.
It does not accept arbitrary shell commands or downloader arguments.
The Telegram bot starts its supervised worker but does not wire the media
dispatcher into Telegram polling.

## V1: manual Debian 12 run (Python 3.11.9)

Run the bot and the offline worker as the **same unprivileged** account,
`tgbot`. No systemd unit or additional worker account is needed for V1.
The worker socket defaults to `/tmp/botdownload-worker/worker.sock`;
the worker creates its private directory with mode 0700 on first start.
An existing directory must be owned by the worker UID and mode 0700.
Never run the worker as root.

From the project directory with dependencies installed, start the worker
in its own terminal (or an existing `tgbot` shell):

```sh
export BOTDOWNLOAD_CLIENT_USER=tgbot
export BOTDOWNLOAD_WORKER_DB="$PWD/data/bot.sqlite"
python -m bot.worker_service
```

Use the same socket path for the broker/IPC client. For a connectivity check
from another `tgbot` terminal:

```sh
python -c 'import asyncio; from pathlib import Path; from bot.worker_ipc import ping; print(asyncio.run(ping(Path("/tmp/botdownload-worker/worker.sock"))))'
```

The SQLite path must be absolute. This worker opens it read-only and does not
write task state; the broker remains responsible for all transitions.
The offline fixture is opt-in and never downloads media. **A manually launched
process is not an OS-level network sandbox.** Do not enable yt-dlp or public
downloads until the network confinement requirements are implemented and
verified on the Debian test server.

A systemd unit remains an optional later deployment task, not a prerequisite
for manual V1 development.

## Before enabling media extraction

A separate, explicitly reviewed worker protocol must restrict requested
operations to validated task IDs and immutable server-side task data.
Never accept arbitrary argv, filesystem paths, or shell commands from the
bot. Implement and test the approved v1 network boundary, denying only IPv4
`127.0.0.0/8` and IPv6 `::1/128` for yt-dlp and children, while preserving
system DNS, Fake-IP routing and required HTTPS. Stronger internal/metadata
network blocking is deferred to v2. Any old all-network-deny systemd unit
is an offline prototype, not the approved media egress policy.
The Telegram bot and its existing download queue remain disabled.


## IPC hardening

The worker rejects duplicate JSON keys, unknown fields, unrecognized
operations, malformed frames, and oversized requests. The socket runtime
directory must be owned by the worker process and must not be
world-writable or a symlink. The client uses a finite positive timeout
and treats missing or malformed responses as failure. These are
defense-in-depth checks. Offline operations remain network-free;
`execute_media` is an experimental test-only operation with a distinct
success response, not an indication that public downloads are enabled.


## Task status IPC (read-only)

A second permitted operation is `{"op":"task_status","version":1,"task_id":123}`.
The worker reads **only** the task's status from an explicitly configured
SQLite database using a read-only connection. It does not claim jobs,
execute extractors, accept URLs or paths, or mutate task state. The bot-side
client is `bot.worker_client.query_task_status`; it is not automatically
called by the Telegram polling process.

To opt into SQLite status lookup, set `BOTDOWNLOAD_WORKER_DB` to an absolute
path readable by the dedicated worker account. Do **not** make the bot's
database or directory world-readable. Prefer a dedicated, access-controlled
read-only snapshot or a future broker-mediated lookup. With the default
systemd unit and ordinary private bot database permissions, lookup returns
`unavailable`; the ping operation still works.

Task claiming and retries remain the broker's responsibility. IPC status
queries are read-only. The `cancel_reservation` operation can revoke a
matching reservation and signal an active offline fixture, but it is not
a production media cancellation protocol. The worker retains read-only
database access; this task-status and cancellation route itself starts no
media download. The separate experimental `execute_media` operation may
start one after the authorized lease check.


## Broker lease lifecycle (not wired to execution)

`bot.worker_leases` now implements a **bot-side** durable lease state
machine for future job dispatch. A trusted broker can offer an already
claimed `downloading` task once, receiving a random 256-bit token.
Only its SHA-256 digest is persisted in `worker_job_leases`. State
transitions use SQLite conditional updates and require a matching token,
unexpired lease and still-active task. Explicit cancellation revokes
the lease; expiry marks abandoned leases without automatically retrying.

This is a **foundation**, not a production media dispatcher. Tokens are
transmitted only for authenticated reservation/fixture operations; the
system worker does not claim tasks or perform media downloads. The broker
reconciles leases at bot startup, but lease expiry is not a substitute
for killing a running process. The old offline systemd example still denies all IP traffic. The separately
invoked media integration path can attempt downloads through its confined
gateway, but this has not been accepted for production use. Do not grant
the worker write access to the bot's database.


## IPC reservation handshake (implemented; media execution test-only)

The trusted broker can call `bot.worker_dispatch.reserve_worker_job`
with a numeric task ID and an opaque lease token. The worker checks the
token against the SHA-256 digest, the unexpired `offered` lease and the
`downloading` task state using **read-only** SQLite access. It accepts
at most one reservation at a time; duplicate requests and unknown tokens
are rejected. `cancel_worker_reservation` revokes the matching
in-memory reservation. The broker can separately use
`worker_leases.transition_job` and `cancel_job` to update durable state.

**Important limitations:** Reservation alone is a non-executing handshake.
The separate, opt-in offline fixture launches a fixed local subprocess;
`execute_media` can run an approved media job after a running-lease check
only in the explicitly invoked experimental path. No Telegram handler or
production queue worker dispatches media jobs.
A successful reserve response does not mean media work started or
completed. Cancellation clears an in-memory reservation only, not a
running subprocess. The broker must persist the corresponding lease
transition; an IPC acknowledgement alone is not a durable state
transition. On worker restart, local reservations are lost and the
broker must reconcile durable leases before any future execution.

The systemd example continues to block all IP networking. Do not
interpret these IPC tests as proof of egress isolation.


## Offline executor prototype and crash reconciliation

`bot.offline_executor.execute_offline_job` is an **opt-in offline test
executor**, not a production media downloader. It runs a fixed Python
command with no shell, in an existing private workspace, with a deadline,
process-group termination on cancellation and basic output checks.
The generated artifact contains only the literal `offline-worker-ok`.
No URLs, downloader arguments, Telegram credentials, or external network
access are accepted. The fixed fixture **is** wired into worker IPC through
`execute_offline`, but it is not wired into production Telegram polling.

`bot.worker_recovery.reconcile_worker_leases` provides an explicit,
transactional broker-side reconciliation operation. It expires stale
leases, revokes reservations for tasks no longer downloading or
processing, and fails downloading tasks whose leases were revoked or
expired. It does not automatically retry downloads or touch ambiguous
Telegram uploads. The bot's startup recovery invokes it before regular interrupted-task
requeueing; there is no background lease-recovery daemon.

These modules are offline building blocks. They do not establish
filesystem, cgroup or network confinement of arbitrary media processes,
and they do not yet deliver files to Telegram. The default Telegram path remains media-disabled; experimental
`execute_media` responses do not establish production readiness.


## Network isolation gate (offline mode only)

`bot.worker_isolation.verify_offline_unit` statically checks that the
example systemd unit preserves the strict **no-IP-network** policy and
other mandatory sandbox settings. Tests reject several relaxed variants.
This is not a live check of systemd's effective settings or of kernel
packet filtering. A systemd drop-in can override the unit; operators
must inspect `systemctl cat botdownload-worker.service` and the
effective properties before deployment.

**Network-capable execution remains disabled.** A production-ready downloader needs independent validation of the approved
v1 egress policy: only IPv4 `127.0.0.0/8` and IPv6 `::1/128` are denied,
while platform HTTPS, system DNS and Fake-IP continue to work. Other
private/link-local/metadata restrictions are explicitly deferred to v2. No DNS/provider-specific bypass or
unrestricted `IPAddressAllow` has been introduced. Until real
isolation and integration tests pass on the target VPS, the worker
must continue reporting `downloads_enabled=false`.


## Broker-side reservation orchestration

`bot.worker_broker.reserve_claimed_task` now combines the durable
SQLite offer, worker IPC acknowledgement and compare-and-swap transition
to `running`. A rejected or ambiguous reservation is revoked in SQLite
before a best-effort IPC cancellation. A claimed task is never
automatically retried after an uncertain IPC outcome.

`revoke_claimed_task` revokes the durable capability. **This does not
terminate a subprocess**, and it cannot notify the worker without the
original plaintext token. The separate offline integration knows its token
and sends `cancel_reservation` explicitly. These broker
helpers are deliberately not connected to the Telegram polling loop.

**Deployment gate:** media execution and external networking remain
disabled. Do not enable downloading based on static unit checks alone.
The experimental `execute_media` path already provides lease-based start
and a file result, but full cancellation, containment, cumulative quotas,
Telegram integration and live v1 loopback checks remain acceptance gates.


## Offline end-to-end integration (opt-in; NOT media)

`bot.offline_queue_integration.process_one_offline_task` exercises a
complete deterministic path: claim a queued task, create a durable lease,
reserve via authenticated Unix IPC, confirm `running`, run a fixed
network-free subprocess in the separate worker, transfer the bounded
result bytes through IPC, mark the lease finished and stage the result
in the existing bot-owned `upload_pending` lifecycle. The worker does
not receive paths, URLs, arguments or SQLite write access. Cancellation
of the active reservation signals the subprocess and its process group
is killed by the offline executor.

This path is deliberately **not started by bot.main**. The fixture is
`offline-result.bin`, not a video or audio file; it must never be
sent to users as media. It tests staging, not actual Telegram delivery.
The worker must have read-only access to the broker's SQLite database
and the containing directory, without write access; configure this
explicitly on a target installation rather than changing permissions
on the bot's private database blindly.

Production media delivery, automatic worker scheduling, crash-safe
cancellation across restarts, and public HTTPS egress isolation remain
separate deployment gates. The systemd unit still denies all IP traffic.


## Startup crash-safety (offline dispatcher)

The bot's startup recovery now reconciles existing worker leases before
requeueing ordinary interrupted tasks. Tasks with a lease are never
automatically requeued, even when the lease expired or was cancelled: an
external worker could still be active. Expired or revoked leased tasks
are marked failed; unexpired leases remain in their existing state pending
operator review. This is a *fail-closed* guard against duplicate execution,
not a way to kill worker subprocesses.

In V1 the bot and worker use the same unprivileged `tgbot` UID.
Configure the worker's read-only SQLite connection using
`BOTDOWNLOAD_WORKER_DB` before testing reservation operations.
