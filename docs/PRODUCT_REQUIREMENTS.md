# Product requirements and portability contract

This document describes product requirements and portability. For security
requirements in v1, the approved [SECURITY_POLICY_V1.md](SECURITY_POLICY_V1.md)
(approved 2026-11-03) takes precedence wherever documents disagree. Changes
to that approved policy require separate owner approval.

## Product scope

- Telegram bot accepting supported HTTPS media links from YouTube, Instagram,
  and TikTok.
- Video output options: 480p, 720p, 1080p where source formats allow them.
  Prefer MP4 with H.264 video and AAC audio for Telegram compatibility.
- Audio-only MP3 output with variable bitrate; prefer Russian audio tracks when
  requested and available. Clearly report unavailable formats or languages.
- A bounded queue with one active worker, at most 20 pending jobs, and a maximum
  wait of 30 minutes.
- Per-user quota of three successful deliveries per UTC day; trusted users are
  exempt. Charge only successful deliveries.
- Reuse Telegram file IDs when safe and applicable.
- Respect the configured Telegram API transport: 50 MB cloud upload limit and
  2000 MB local Bot API limit, including preflight size checks.
- Retries, temporary-file cleanup, admin controls, and understandable Russian
  user-facing errors.

## Installation and portability

1. A fresh supported Linux VPS must be able to clone the repository, configure
   secrets, install documented dependencies, and start the bot without editing
   Python source code. Debian is the primary test platform; do not depend on
   any particular office router, DNS server, host IP, provider, or firewall.
2. Keep credentials in environment variables or ignored local secret files.
   Ship documented examples, not real secrets. Preserve existing user config
   across updates.
3. Support a reproducible deployment path with systemd and/or Docker Compose.
   Document supported OS/Python versions, dependencies, service lifecycle,
   data persistence, backups, and upgrades. Do not claim a platform is supported
   without testing it.
4. Use the operating system's resolver by default. Never hard-code a public DNS
   resolver or change the host's routes to fix a site-specific DNS issue.
   The approved v1 network policy explicitly allows private, link-local and
   Fake-IP ranges other than IPv4 127.0.0.0/8 and IPv6 ::1/128; stricter
   network blocking is deferred to v2.
5. Deployment checks must distinguish portable security requirements from
   environment-specific diagnostics. A test on an office server is not proof
   that a different VPS has identical DNS, routing, or cgroup features.

## Security and process architecture

1. Treat media URLs and extractor-controlled URLs as untrusted. HTTPS and
   allowed-host validation plus DNS preflight are defense in depth, not a
   sufficient SSRF boundary. Validate approved destinations and apply the v1
   loopback-only network restriction to yt-dlp and its child processes,
   including internal and redirected requests. The residual SSRF risk to
   other internal addresses is explicitly accepted for v1.
2. Run the Telegram bot as an unprivileged account. Never require the bot to
   run as root or give it unrestricted access to the systemd system manager.
3. Run network-capable media extraction and downloading in a separately
   confined worker with explicit resource, filesystem, and egress limits.
   Privileged setup, if required, belongs to a documented installation step,
   not a privilege escalation path available to untrusted chat messages.
4. For v1 network connections made by yt-dlp and its children, block **only**
   IPv4 127.0.0.0/8 and IPv6 ::1/128. Do not block other private IPv4/IPv6,
   link-local, cloud metadata or Fake-IP 198.18.0.0/15 in v1. Verify the
   actual loopback denial and working DNS/allowed media traffic on the target
   deployment. Stronger private-network SSRF protection is deferred to v2.
   Do not silently disable the v1 isolation when unsupported.
5. Timeouts must terminate worker processes; enforce output and file-size
   limits; avoid shell command construction; isolate per-job temporary files.
6. Network probes are diagnostics only. Passing one probe does not certify
   protection against all SSRF paths.

## Delivery priorities

1. Build a deployable, least-privilege worker boundary that works across VPS
   environments, including a documented installation and readiness check.
2. Integrate the isolated metadata and download workers with the Telegram
   handler and queue.
3. Implement delivery, quotas, caching, retries, and administrative operations.
4. Validate on a clean VPS and document operational and security limitations.

## Development workflow

- Work in feature branches and review changes before merging into main.
- Keep tests deterministic and offline where possible; mark live integration
  checks explicitly opt-in.
- Never overwrite a user's local config.yaml or .env during an update.
- Keep the README aligned with actual functionality, not intended functionality.
