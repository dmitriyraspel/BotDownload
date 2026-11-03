# Network isolation: deployment gate

**Status: not deployable for untrusted links.** The bot now refuses metadata
inspection unless a process network guard is explicitly provided. Download
execution likewise requires a guard. A guard that merely prefixes argv is
**not proof** of enforced isolation.

## Required deployment architecture

- Telegram polling runs as a non-root service account.
- Networked metadata and downloads run in a **separate** process with an
  OS-enforced outbound policy; neither the Telegram bot nor user-supplied
  links may configure privileged systemd units.
- Restrict loopback, RFC1918, link-local, cloud metadata addresses, IPv6
  private/link-local and reserved ranges, including redirects and internal
  yt-dlp requests. Allow public HTTPS and DNS through the host resolver.
- Bound CPU, memory, process count, disk output, duration, filesystem access
  and per-job temporary directories. Never disable restrictions on failure.
- The installation procedure must configure a root-owned unit or equivalent
  once, during deployment, not at request time. Validate permissions and
  provide an unprivileged invocation path before enabling processing.

## Existing diagnostics

The modules `bot.egress_loopback_probe` and `bot.egress_public_probe`
exercise a *privileged, transient* systemd experiment. They are diagnostics
only, **not** a production invocation path for the unprivileged bot. The
public HTTPS probe may fail when a systemd IP filter also blocks the local
DNS stub; do not solve this by hard-coding public DNS or permitting all
private addresses.

The following are **mandatory** on each target VPS before enabling the
feature: a reachable local baseline, denied IPv4/IPv6 loopback and private
egress under the same service policy, working DNS and public HTTPS under
confinement, and verification that the bot account cannot weaken the policy.

A portable production service/socket boundary and end-to-end verification
are still outstanding. The current branch must not be advertised as ready
for public use.
