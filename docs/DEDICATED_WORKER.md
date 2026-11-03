# Dedicated worker IPC: experimental, downloads disabled

The first independent worker is implemented in `bot.worker_service`. It
accepts **only** `{"op":"ping","version":1}` over a local Unix socket.
It never executes arbitrary commands, processes URLs, or downloads media.
The Telegram bot does not start this service automatically.

## Optional Debian 12 installation (administrator only)

The example assumes the repository lives in `/opt/BotDownload`. Adjust the
systemd unit's `WorkingDirectory` and `ExecStart` for another location;
never change Python sources or overwrite local `config.yaml`.

1. Create an unprivileged worker account, **different** from the bot account.
   For example, as root:
   `useradd --system --no-create-home --shell /usr/sbin/nologin --gid tgbot botdownload-worker`
   (the `tgbot` group and bot user must already exist).
2. Install `deploy/botdownload-worker.service.example` as
   `/etc/systemd/system/botdownload-worker.service`, after reviewing paths
   and the actual service user/group.
3. Run `systemctl daemon-reload` and
   `systemctl enable --now botdownload-worker.service`.
4. The socket is `/run/botdownload-worker/worker.sock`, inside a
   systemd-managed runtime directory. It is group-accessible, but the
   service checks the connecting process's **kernel-provided UID** against
   `BOTDOWNLOAD_CLIENT_USER=tgbot`. No client-supplied UID is trusted.
5. To check IPC from the bot account:
   `sudo -u tgbot /opt/BotDownload/.venv/bin/python -c 'import asyncio; from pathlib import Path; from bot.worker_ipc import ping; print(asyncio.run(ping(Path("/run/botdownload-worker/worker.sock"))))'`
   Run from the project directory or with its package import path set.

The unit denies **all IP traffic** (`IPAddressDeny=any`,
`RestrictAddressFamilies=AF_UNIX`). This is deliberate: it does not yet
host a network-capable extractor. A successful ping establishes only that
the local IPC channel is working, not that download egress is safe.

## Before enabling media extraction

A separate, explicitly reviewed worker protocol must restrict requested
operations to validated task IDs and immutable server-side task data.
Never accept arbitrary argv, filesystem paths, or shell commands from the
bot. Implement and test an enforced network boundary that permits public
HTTPS and legitimate DNS while blocking internal and metadata networks,
including redirects and DNS rebinding. The service's current all-network
deny must not be relaxed until live negative and positive checks pass.
The Telegram bot and its existing download queue remain disabled.


## IPC hardening

The worker rejects duplicate JSON keys, unknown fields, unrecognized
operations, malformed frames, and oversized requests. The socket runtime
directory must be owned by the worker process and must not be
world-writable or a symlink. The client uses a finite positive timeout
and treats missing or malformed responses as failure. These are
defense-in-depth checks; the IPC protocol still exposes only ping.


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

Cancellation, retries, task claiming and media execution are deliberately
**not** implemented in this protocol yet. An IPC status query cannot cancel
a running job; no download is started. This avoids granting the worker
unnecessary database write privileges before the full job lifecycle and
network confinement are reviewed.


## Broker lease lifecycle (not wired to execution)

`bot.worker_leases` now implements a **bot-side** durable lease state
machine for future job dispatch. A trusted broker can offer an already
claimed `downloading` task once, receiving a random 256-bit token.
Only its SHA-256 digest is persisted in `worker_job_leases`. State
transitions use SQLite conditional updates and require a matching token,
unexpired lease and still-active task. Explicit cancellation revokes
the lease; expiry marks abandoned leases without automatically retrying.

This is a **foundation**, not a running job dispatcher. Tokens are not
yet transmitted over IPC, the system worker does not claim tasks,
process files, or terminate subprocesses, and no automatic recovery
of lease-owned jobs is installed. In particular, lease expiry is
not a substitute for killing a running process. The separate worker
still denies all IP traffic and cannot download media. Do not grant
the worker write access to the bot's database.


## IPC reservation handshake (implemented, execution disabled)

The trusted broker can call `bot.worker_dispatch.reserve_worker_job`
with a numeric task ID and an opaque lease token. The worker checks the
token against the SHA-256 digest, the unexpired `offered` lease and the
`downloading` task state using **read-only** SQLite access. It accepts
at most one reservation at a time; duplicate requests and unknown tokens
are rejected. `cancel_worker_reservation` revokes the matching
in-memory reservation. The broker can separately use
`worker_leases.transition_job` and `cancel_job` to update durable state.

**Important limitations:** This is a non-executing handshake only.
No Telegram handler or queue worker dispatches jobs automatically.
The worker does not download, create output files, or launch processes.
A successful reserve response does not mean media work started or
completed. Cancellation clears an in-memory reservation only, not a
running subprocess. The broker must persist the corresponding lease
transition; an IPC acknowledgement alone is not a durable state
transition. On worker restart, local reservations are lost and the
broker must reconcile durable leases before any future execution.

The systemd example continues to block all IP networking. Do not
interpret these IPC tests as proof of egress isolation.
