# Changelog

All notable changes to PocketLinux (`plx`) are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-11-10

First complete release. Everything below is implemented, tested and documented.

### Added

* **Rootfs provisioning** — Ubuntu Base 24.04 and Alpine 3.20 images (aarch64 / armv7 / x86_64 /
  i686), Debian/Kali/Arch/Void/Fedora/openSUSE via `proot-distro`, plus `--url` for any tarball.
  Architecture detection, free-space guard, cached downloads, `--force`, `--dest`, `--dry-run`.
* **Two shell engines** — `proot` (no root) and `chroot` under `su`, the latter running bind mounts
  in a private mount namespace with real read-only remounts.
* **Bind-mount planner** — `/dev`, `/proc`, `/sys`, shared storage, user extras (`src:dst[:ro]`),
  optional/skipped sources, and `plx mount show --command` for the exact argv.
* **`plxd` supervisor** — restart policies (`always`/`on-failure`/`never`), sliding-window restart
  limits, per-service log files with 5 MiB rotation, JSON state mirroring, UNIX-socket JSON control
  protocol, graceful shutdown of whole process groups, PID/socket cleanup.
* **Service definitions** — `~/.plx/services.toml` with commands, dirs, env, timeouts, signals;
  `plx service up|down|ls|status|start|stop|restart|logs|reload|edit|example|daemon`.
* **Recipes** — declarative environments with packages (apt/apk/pip/npm), hooks, services, env and
  mount suggestions; bundled `devbox`, `datascience`, `webdev`, `minimal`; step-by-step JSON
  reports.
* **Hardware bridge** — 20 Termux:API tools (battery, Wi-Fi, sensors, location, torch, clipboard,
  notifications, vibrate, camera, TTS, volume, brightness, wake locks, telephony, SMS, share,
  open) with structured output and permission-aware errors.
* **Snapshots** — `tar` based create/list/verify/restore/prune with SHA-256 manifests, zstd/gzip
  support, previous rootfs kept aside on restore, dry-run everywhere.
* **Networking** — address/port inventory, ed25519 key generation, safe-by-default
  `sshd_config` (loopback, key-only), SSH session info, `net doctor`.
* **Security posture** — verified-boot/SELinux/debuggable/ADB-over-network/port-exposure findings
  with severities, scope statement, and a hardening plan that only applies with `--apply`.
* **Desktop** — optional Termux:X11 orchestration (`status|start|stop|session`) for XFCE/LXQt/
  MATE/Fluxbox/Openbox/xterm.
* **Diagnostics** — `plx doctor` with 17 checks and copy-pasteable fixes; `plx info`.
* **Config** — validated TOML with warnings instead of crashes, `config set` with type coercion.
* **UX** — `--json` on every command, `--dry-run` on every mutation, adaptive tables, colour
  detection, one-line errors naming the fix.
* **Tooling** — `install.sh` Termux bootstrap, `bin/plx` launcher (works from a checkout),
  Termux:Boot hook, bash completion, Makefile, CI for Python 3.11–3.13, 140+ tests including a real
  daemon integration test.
* **Docs** — README plus 13 documents: overview, quickstart, architecture, rootfs/engines,
  hardware, services, recipes, networking, desktop, security & limits, troubleshooting, FAQ, CLI
  reference.

### Security

* `~/.plx` created `0700`; guest keys `0600`; control socket `0600`.
* sshd defaults to loopback + `PasswordAuthentication no`.
* Backups are hash-verified before restore; unsafe removal paths are refused.
* No exploit code, no privilege escalation, no writes to `/system` — see
  [docs/09-security-and-limits.md](docs/09-security-and-limits.md).
