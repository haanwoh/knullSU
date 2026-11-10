# 03 · Rootfs & engines

Two independent choices decide what `plx shell` does:

1. **which root filesystem** you run (Ubuntu, Alpine, Debian, a tarball you built);
2. **which engine** executes it (`proot`, or `chroot` under `su`).

## Rootfs sources

| distro | method | architectures | size |
|---|---|---|---|
| `ubuntu` 24.04.1 Base | official cdimage tarball | aarch64, x86_64, armv7 | ~1.5 GiB extracted |
| `alpine` 3.20.3 minirootfs | official mirror | aarch64, x86_64, armv7, i686 | ~150 MiB |
| `debian`, `kali`, `archlinux`, `void`, `fedora`, `opensuse` | `proot-distro` | whatever proot-distro supports | varies |
| anything | `plx install --url …` | yours | yours |

```bash
plx install --list
plx install ubuntu --arch aarch64
plx install alpine --dest /data/local/tmp/alpine
plx install --url https://example.org/rootfs.tar.gz
plx install ubuntu --force            # wipe and reinstall
plx install ubuntu --dry-run          # print the plan
```

Pinned URLs live in `plx/rootfs.py::IMAGES` — one dict, no scraping, no "latest" surprises.
Bump them in a PR when a new point release ships.

### What `install` writes

| path | why |
|---|---|
| `etc/resolv.conf` | proot cannot use Android's resolver socket; public DNS makes `apt` work |
| `etc/hosts`, `etc/hostname` | avoids "unable to resolve host" delays |
| `etc/plx-release` | provenance: distro, plx version, engine, host model, timestamp |
| `etc/profile.d/plx.sh` | `PATH`, aliases, `PLX_GUEST=1` |
| `etc/apt/apt.conf.d/99-plx-sandbox` | `APT::Sandbox::User "root"` — proot cannot setuid to `_apt` |
| `root/.ssh` | `0700`, ready for `plx net ssh` |
| `root/{downloads,projects}`, `mnt/storage` | conventional landing spots |

## Engines

### `proot` (default, no root)

```console
$ plx shell --dry-run
[dry-run] proot -0 --link2symlink --kill-on-exit -r ~/.plx/rootfs/ubuntu -w /root \
  -b /dev -b /proc -b /sys -b /storage/emulated/0:/mnt/storage \
  /usr/bin/env -i HOME=/root PATH=/usr/local/sbin:… TERM=xterm-256color LANG=C.UTF-8 \
  HOSTNAME=pocketlinux PLX_HOST=1 /bin/bash -l
```

Key flags:

* `-0` — present as uid 0 inside the guest (required by `apt`, `sshd`, `passwd`).
* `--link2symlink` — hard links become symlinks; Android's storage cannot hard-link.
* `--kill-on-exit` — no orphaned guests when the phone kills your shell.
* `-b src:dst` — bind mounts, emulated by proot.

Limitations worth knowing:

* syscall-heavy workloads are 2-10× slower than native (compiling, `apt` with many packages);
* `ptrace`-based debuggers and some JITs misbehave;
* `read-only` binds are **not** enforced (proot has no `ro` concept) — the guest *can* write;
* no real `setuid`, so `sudo` inside the guest is meaningless (you are already root).

### `chroot` (rooted devices, `su` present)

```bash
plx shell --engine chroot
plx config set core.engine chroot    # make it the default
```

`mounts.chroot_script()` builds a script that:

1. enters a private mount namespace (`unshare -m --propagation private`) — the host never sees
   the mounts, and a kill -9 cannot leave them behind;
2. bind-mounts `/dev`, `/proc`, `/sys`, storage and your extras (`ro` extras get
   `mount -o remount,bind,ro`, so read-only is *real* here);
3. `chroot`s and execs your shell.

This runs through `su -c '…'`, so your root manager (Magisk, KernelSU, `tsu`) prompts once.

## Bind mounts

```console
$ plx mount show
  engine   proot (available)
  rootfs   ~/.plx/rootfs/ubuntu
  workdir  /root

source                              guest path     mode
──────────────────────────────────  ─────────────  ────
/dev                                /dev           rw
/proc                               /proc          rw
/sys                                /sys           rw
/storage/emulated/0                 /mnt/storage   rw
/sdcard/Download                    /root/downloads rw
```

Rules:

* `src:dst` — read-write; `src:dst:ro` — read-only (enforced on chroot, advisory on proot);
* a source that does not exist is **skipped with a note**, never a hard failure
  (`optional=True`), so a config written on one phone still works on another;
* `mounts.storage = false` removes the shared-storage bind entirely (useful for a jail-ish setup);
* `plx mount show --command` prints the final engine argv.

## Workdir, shell, hostname

```bash
plx config set core.workdir /root/projects
plx config set core.shell   /bin/sh          # Alpine has no bash by default
plx config set core.hostname pocket
```

If the configured shell is missing inside the rootfs, `plx` warns and falls back to `/bin/sh`
instead of failing.

## Rebuilding safely

```bash
plx backup create --label before-upgrade
plx rootfs status
plx install ubuntu --force        # wipes ~/.plx/rootfs/ubuntu
plx backup restore ~/.plx/backups/plx-ubuntu-…-before-upgrade.tar.zst --yes
```

`plx rootfs remove --yes` deletes the rootfs but keeps backups, cache and config.
