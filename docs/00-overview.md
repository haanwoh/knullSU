# 00 · Overview

PocketLinux (`plx`) is a small, deliberately boring tool that makes a phone behave like a
Linux host you administer: a root filesystem you can wipe and rebuild, a shell with sane
`/dev`, `/proc` and `/sys`, a process supervisor that survives crashes, and backups you can
verify.

It is **not** a rooting tool. There is no exploit code in this repository, and none is planned.
See [09 · Security & limits](09-security-and-limits.md) for the full boundary.

## Who this is for

* developers who want a real `gcc`/`python`/`node` toolchain in their pocket;
* sysadmins who want `ssh` into their own phone and a supervised `sshd`/dev server;
* anyone curious how far a stock Android device can go without flashing anything;
* people who tried `proot-distro` and got lost in bind mounts, DNS and orphaned processes.

## What "ground-level access" means here

| layer | stock Termux | PocketLinux |
|---|---|---|
| Filesystem | one shared `$HOME` | isolated rootfs per distro, wipe/rebuild in seconds |
| Package manager | `pkg` only | `apt`/`apk` inside the guest, plus `pip`, `npm` |
| Processes | whatever is in your shell | `plxd`: restart policies, backoff, per-service logs |
| Hardware | individual `termux-*` calls | one `plx hw` interface with structured output |
| Recovery | copy files by hand | SHA-256-verified snapshots, restore with previous rootfs kept aside |
| Visibility | guesswork | `plx doctor`, `plx security report`, `--json` everywhere |

That is *depth*: every layer above is a real Linux mechanism, not a mock. Root (kernel-level
control of the Android host) is a different thing entirely, and this project does not provide it.

## Design principles

1. **Stdlib-only.** Python 3.11+, zero runtime dependencies. A phone upgrade must never break
   `plx` because a transitive wheel vanished.
2. **One home directory.** Everything lives in `~/.plx` (override with `PLX_HOME`), created
   `0700`. Delete the directory and you are back to a clean phone.
3. **Preview before action.** `--dry-run` on every mutation, `plx mount show` for the exact
   argv, `plx security harden` shows a plan until you pass `--apply`.
4. **Machine-readable.** Every command has `--json`; the same data drives human output.
5. **Fail with a fix.** Errors name the missing binary and the command that installs it.
6. **No magic.** `plxd` is readable in one sitting; bind mounts are a list you can print.

## Requirements

* Android 9+ (Termux works on 7+, proot is happiest on 9+)
* Termux from **F-Droid** or GitHub releases — the Play Store build is deprecated
* ~200 MiB free for Alpine, ~1.5 GiB for Ubuntu, plus your packages
* Optional: Termux:API app (hardware bridge), Termux:Boot (start services at boot),
  Termux:X11 (desktop)

## The 60-second version

```bash
plx doctor                 # what works, what is missing, how to fix it
plx install alpine         # rootfs in seconds
plx shell                  # enter it
plx recipe apply devbox    # or a full toolchain
plx service up             # supervised background services
plx backup create          # snapshot before you break something
```

Next: [01 · Quickstart](01-quickstart.md).
