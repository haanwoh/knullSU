# 01 · Quickstart

## 0. Prerequisites

Install **Termux from F-Droid** (or the GitHub releases page). The Play Store build has been
deprecated for years and will fail in confusing ways.

```bash
pkg update && pkg upgrade
```

Do not install `proot` by hand — the installer does it, and version matters.

## 1. Install PocketLinux

```bash
curl -fsSL https://raw.githubusercontent.com/haanwoh/knullSU/main/install.sh | bash
```

The installer:

1. verifies you are in Termux (override with `--force`),
2. `pkg install python proot termux-api openssh rsync tar zstd curl git`,
3. symlinks `bin/plx` into `~/.local/bin/plx` and fixes `PATH` in `~/.bashrc`,
4. writes `~/.plx/config.toml`,
5. runs `plx doctor`.

From a checkout, skip the script:

```bash
git clone https://github.com/haanwoh/knullSU && cd knullSU
./bin/plx doctor
```

## 2. Run the self-check

```bash
plx doctor
```

Expected first-run output on a fresh phone (abridged):

```console
✓  Python runtime        3.12.7 (/data/data/com.termux/files/usr/bin/python3)
✓  Host device          Google Pixel 7 · Android 15 · aarch64
✓  CPU architecture     aarch64
✗  Selected engine      config says proot but proot is missing
✗  proot engine         proot not found
!  Termux:API bridge    termux-api CLI or the Termux:API app is missing
!  Shared storage       no shared storage path visible
✓  Free space           41.2 GiB free on /data
!  Root filesystem      nothing installed at ~/.plx/rootfs/ubuntu
!  plxd supervisor      not running
...
suggested fixes
  proot engine: pkg install proot
  Shared storage: termux-setup-storage
  Root filesystem: plx install ubuntu
```

Fix the failing ones, re-run until `plx doctor` exits 0. `--json` gives the same data for CI.

## 3. Install a root filesystem

```bash
plx install --list          # what is available for your CPU
plx install alpine          # ~150 MiB, seconds
plx install ubuntu          # ~1.5 GiB, full apt ecosystem
plx install debian          # via proot-distro, if installed
plx install --url https://example.com/rootfs.tar.gz   # anything
```

What happens under the hood:

1. architecture detection (`aarch64`, `armv7`, `x86_64`, `i686`),
2. free-space check (needs ~1.5 GiB for Ubuntu; Alpine is exempt in practice),
3. download to `~/.plx/cache/` (kept for reinstalls),
4. `tar -xf … --no-same-owner` into `~/.plx/rootfs/<distro>` — no root needed,
5. post-configure: `/etc/resolv.conf`, `/etc/hosts`, `/etc/hostname`, `/etc/plx-release`,
   `/etc/profile.d/plx.sh`, `apt` sandbox fix, `root/.ssh` at `0700`.

## 4. Enter it

```bash
plx shell
```

```console
→ ubuntu · engine proot · ~/.plx/rootfs/ubuntu
root@pocketlinux:~# apt update && apt install -y git curl
root@pocketlinux:~# exit
```

One-off commands:

```bash
plx exec uname -a
plx shell -c 'apt list --installed | wc -l'
```

See exactly what will run, without running it:

```bash
plx shell --dry-run
plx mount show --command
```

## 5. Storage

`termux-setup-storage` once, then your shared storage is bind-mounted at `/mnt/storage`
inside the guest. Add your own:

```bash
plx config set mounts.extra "/sdcard/Download:/root/downloads"
plx config set mounts.extra "/sdcard/Documents:/root/documents:ro"   # read-only
plx mount show
```

## 6. Services

```bash
plx service example        # writes a commented template
plx service edit           # $EDITOR, validates, reloads
plx service up             # start the supervisor
plx service status
plx service logs sshd -n 50
plx service down
```

Start `plxd` automatically at boot: copy [`scripts/termux-boot.sh`](../scripts/termux-boot.sh)
into `~/.termux/boot/` (needs the Termux:Boot app).

## 7. Snapshots

```bash
plx backup create --compress zstd --prune 5
plx backup ls
plx backup verify ~/.plx/backups/plx-ubuntu-20261110-120455.tar.zst
plx backup restore ~/.plx/backups/... --yes
```

Restore keeps the previous rootfs as `ubuntu.pre-restore-<timestamp>` — nothing is destroyed
until you delete it yourself.

## Common first-run pitfalls

| symptom | cause | fix |
|---|---|---|
| `proot: not found` | package missing | `pkg install proot` |
| `apt update` fails with `Could not resolve` | no DNS inside guest | `plx install --force` (rewrites resolv.conf), or check Wi-Fi |
| `Permission denied` writing `/sdcard` | storage not granted | `termux-setup-storage`, then re-open Termux |
| `apt` warns `unsandboxed as root` | known proot limitation | already handled by `/etc/apt/apt.conf.d/99-plx-sandbox` |
| commands killed after switching apps | Android froze Termux | `termux-wake-lock`, or add the wake lock to your boot script |
| `plxd` unreachable after reboot | not started | `plx service up` / Termux:Boot |

More: [10 · Troubleshooting](10-troubleshooting.md).
