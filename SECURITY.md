# Security policy

## Scope

PocketLinux runs as an unprivileged Android app (Termux). In scope for security reports:

* escaping the guest filesystem into paths outside the bind mounts;
* command injection through config values, recipe fields, service commands, or file names;
* world-readable/writable files created outside the documented `0700`/`0600` modes;
* the control socket (`plxd.sock`) accepting commands from another app/uid;
* backup manifests that can be made to pass verification when the archive is corrupt;
* any path traversal in `backup restore`, `install --url`, or `recipe copy`.

**Out of scope:** the fact that PocketLinux cannot root a phone, cannot bypass Android's app
sandbox, and cannot protect data on a device that is already rooted or has an unlocked bootloader.
Those are design boundaries, documented in [docs/09-security-and-limits.md](docs/09-security-and-limits.md).

## Reporting

Please **do not** open a public issue. Email the maintainers (or use GitHub's private "Report a
vulnerability" advisory flow on the repository) with:

1. affected version (`plx version --json`);
2. a minimal reproduction (commands, config, expected vs actual);
3. impact assessment — what an attacker gains and what access they need first.

We aim to acknowledge within 72 hours and to ship a fix (with a test) within 14 days for
high-severity issues. Credit is given in `CHANGELOG.md` unless you prefer otherwise.

## Hardening checklist for users

```bash
plx security report                 # facts, not reassurance
plx security harden --apply         # loopback sshd, key-only, 0700 ~/.plx
plx config set net.ssh_bind 127.0.0.1
plx backup create --compress zstd   # before any upgrade
```

Keep Termux and the Termux:API app from F-Droid, never from random APK mirrors.
