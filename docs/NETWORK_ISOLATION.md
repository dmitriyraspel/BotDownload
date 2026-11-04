# Network isolation: deployment gate (approved v1 policy)

**Normative reference:** [SECURITY_POLICY_V1.md](SECURITY_POLICY_V1.md),
sections 5, 6, 9 and 10, takes precedence over earlier design notes.

**Status: not deployable for untrusted links.** The bot now refuses metadata
inspection unless a process network guard is explicitly provided. Download
execution likewise requires a guard. A guard that merely prefixes argv is
**not proof** of enforced isolation.

## Required deployment architecture

- Telegram polling runs as a non-root service account.
- Networked metadata and downloads run in a **separate** process with an
  OS-enforced outbound policy; neither the Telegram bot nor user-supplied
  links may configure privileged systemd units.
- In v1 block **only** IPv4 `127.0.0.0/8` and IPv6 `::1/128`
  for yt-dlp and its children, including redirected and internal requests.
  Other private/link-local/metadata and Fake-IP `198.18.0.0/15` addresses
  remain permitted under the approved v1 policy; stricter blocking is v2.
  Keep OS DNS and existing routes unchanged.
- Bound CPU, memory, process count, disk output, duration, filesystem access
  and per-job temporary directories. Never disable restrictions on failure.
- Run the service under one unprivileged Linux UID in v1. Additional service
  UIDs and a mandatory privileged/root-owned systemd unit are not v1
  requirements. Any optional OS setup must be administrative, never controlled
  by user input.

## Existing diagnostics

The modules `bot.egress_loopback_probe` and `bot.egress_public_probe`
exercise a *privileged, transient* systemd experiment. They are diagnostics
only, **not** a production invocation path for the unprivileged bot. The
public HTTPS probe may fail when a systemd IP filter also blocks the local
DNS stub; do not solve this by hard-coding public DNS or permitting all
private addresses.

Before enabling on each deployment, verify denied IPv4 `127/8` and IPv6
`::1` connections **from yt-dlp and children**, plus working OS DNS and
allowed media HTTPS (including Fake-IP where deployed). Verify the service
runs unprivileged and that worker failure never falls back to unconfined
execution. The approved v1 policy explicitly records incomplete SSRF
protection for other private or metadata addresses.

A portable production service/socket boundary and end-to-end verification
are still outstanding. The current branch must not be advertised as ready
for public use.
