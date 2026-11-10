# 09 · Security & limits

This page is the honest one. Read it before you trust anything on the internet about "full phone
access".

## What PocketLinux is

A workstation manager for **hardware you own**: it provisions a Linux root filesystem, runs a
shell inside it, supervises services, exposes documented hardware interfaces, and takes backups.

## What PocketLinux is not

| claim you may have read | reality |
|---|---|
| "roots any Android phone" | No. There is no exploit code here, and none is planned. Rooting requires a device-specific vulnerability or an unlocked bootloader. |
| "gives 100% control of any device" | No. `plx` only touches the device it runs on, with the permissions Android granted. |
| "flash it on a phone and the phone is yours" | No. PocketLinux is not a boot image or a ROM; it runs *inside* Android as a normal app. |
| "bypasses lock screens / FRP" | No. |
| "extracts data from other apps" | No. Android's per-app sandbox still applies; Termux:API only exposes what you granted. |

If someone offers you a "universal root method" as a single file, it is either a scam, malware, or
both. Real rooting is device-specific work with real risk (bricked devices, broken DRM/banking
apps, no more OTA updates).

## Threat model

**In scope** — things `plx` defends against:

* *Accidental self-damage*: a broken rootfs is one `plx install --force` or `plx backup restore`
  away; the previous rootfs is kept aside, never deleted in place.
* *Truncated backups*: every archive gets a SHA-256 manifest, checked on restore.
* *Stray processes*: children run in their own sessions and are killed by process group.
* *Network exposure by accident*: `sshd_config` defaults to loopback + key-only; the security
  report flags any `0.0.0.0` bind, every run.
* *Secret sprawl*: `~/.plx` is created `0700`; keys are `0600`; the control socket is `0600`.
* *Silent change*: every mutation has `--dry-run`; `plx security harden` prints a plan and changes
  nothing without `--apply`.

**Out of scope** — things `plx` cannot defend against:

* an unlocked bootloader (anyone with 30 seconds and a cable can reflash your phone);
* a compromised Android host, a malicious root manager, or a malicious Termux build;
* other apps reading your screen, or a keyboard logger in a custom ROM;
* physical access with a debug cable;
* a rooted device where any app with `su` can read `~/.plx` anyway.

`plx doctor` and `plx security report` give you the facts (verified-boot state, SELinux, ADB over
network, exposed ports) so you can make your own call.

## Reading `plx security report`

```console
$ plx security report
  verified boot   orange — bootloader unlocked (dm-verity may be off)
  selinux         enforcing
  security patch  2026-10-05
  worst finding   medium

findings
severity  finding                        detail
────────  ───────────────────────────  ──────────────────────────────────────
medium    Bootloader is unlocked       Anyone with physical access …
info      SELinux enforcing            Mandatory access control is on.
low       4 port(s) listening on all interfaces  tcp: 8022, 8000 …
```

Severities are deliberately conservative: an unlocked bootloader is *informational* for a
development phone and *serious* for a daily driver. The report tells you; it does not decide
for you.

## Hardening

```bash
plx security harden --dry-run     # the plan
plx security harden --apply       # write sshd_config, chmod keys and ~/.plx
```

What `--apply` does:

* writes `etc/ssh/sshd_config` inside the guest: `PasswordAuthentication no`,
  `PermitRootLogin prohibit-password`, `MaxAuthTries 4`, no X11 forwarding, no tunnelling;
* `chmod 700` on `~/.plx` and `root/.ssh`, `chmod 600` on the guest key;
* nothing else. It will not disable ADB, re-lock your bootloader, or change Android settings —
  those are your decisions, and some of them are irreversible.

## Data you should know about

| location | contents | sensitivity |
|---|---|---|
| `~/.plx/rootfs` | a whole Linux userland, possibly with your keys/tokens inside | high |
| `~/.plx/backups` | full snapshots (the same data, compressed) | high |
| `~/.plx/logs` | service output — may contain URLs, tokens if your app logs them | medium |
| `~/.plx/state` | PIDs and JSON status | low |
| `~/.plx/config.toml`, `services.toml` | paths, commands | low |

`plx backup` archives are **not encrypted**. If you copy them off-device, encrypt them yourself
(`age`, `gpg`), and remember that Termux's `$HOME` is inside the app sandbox, readable by any app
with root.

## Responsible disclosure

Found something that breaks the security model (a way to escape the guest, a command-injection in
a path, a world-readable key)? See [SECURITY.md](../SECURITY.md). Please do not open a public
issue for it.
