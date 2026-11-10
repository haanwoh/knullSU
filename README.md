# PocketLinux · `plx`

**A real Linux workstation inside your own Android phone — rootfs, shell engines, a service
supervisor, a hardware bridge, reproducible environments and one-command backups.**

[![CI](https://github.com/haanwoh/knullSU/actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

---

## Ye kya hai (short, Hinglish)

Phone ko **Linux machine** bana deta hai — bina root, bina custom ROM, bina kuch flash kiye.
`plx` ek hi command se: Debian/Ubuntu/Alpine rootfs install karta hai, usme ghusne deta hai,
background services (sshd, dev server, Jupyter) ko supervise karta hai, phone ke sensors/camera/
torch/clipboard ko shell se access karta hai, poora rootfs ka backup/restore karta hai, aur
device ka honest security posture dikhata hai.

> **Scope, saaf-saaf:** PocketLinux kisi bhi phone ko *root nahi karta*, bootloader unlock nahi
> karta, lock screen bypass nahi karta, aur kisi doosre device ka control nahi leta. Woh cheez
> exploit-chain / malware hoti hai aur is project ka hissa **nahi** hai. Jo milta hai woh yeh:
> apne hi phone par Linux jaisa **ground-level control** — real root filesystem, real service tree,
> real hardware access. Details: [docs/09-security-and-limits.md](docs/09-security-and-limits.md).

---

## What it actually is

PocketLinux turns Termux into a proper little Linux box:

| | what `plx` gives you |
|---|---|
| **Rootfs** | Ubuntu Base / Alpine tarballs (arch-detected), Debian/Kali/Arch via `proot-distro`, or any tarball with `--url` |
| **Shell** | `proot` engine (no root) or `chroot` engine under `su`, with `/dev`, `/proc`, `/sys` and shared storage bind-mounted |
| **Services** | `plxd`, a ~300-line supervisor: restart policies, bounded backoff, per-service logs, JSON state, UNIX-socket control |
| **Hardware** | battery, Wi-Fi, sensors, GPS, torch, clipboard, notifications, vibration, camera, TTS, volume, brightness, wake-lock — via Termux:API permissions |
| **Recipes** | declarative TOML environments: `devbox`, `datascience`, `webdev`, `minimal` |
| **Backups** | SHA-256-verified tar.zst snapshots with manifest, restore with the previous rootfs kept aside |
| **Networking** | SSH keys, safe-by-default `sshd_config` (loopback + key-only), port inventory |
| **Security** | verified-boot / SELinux / ADB-over-network findings, plus a hardening plan you must explicitly `--apply` |
| **Desktop** | optional Termux:X11 + XFCE/LXQt session |

Everything is **stdlib-only Python 3.11+**: no wheels to build on a phone, no dependency drift.

## Quickstart (2 minutes)

```bash
# 1. install (Termux from F-Droid, not the Play Store build)
curl -fsSL https://raw.githubusercontent.com/haanwoh/knullSU/main/install.sh | bash

# 2. verify
plx doctor

# 3. get a Linux userland — Alpine is ~150 MiB and installs in seconds
plx install alpine
plx shell

# …or the full Ubuntu experience (~1.5 GiB)
plx install ubuntu
plx recipe apply devbox
```

From a git checkout, no install step is needed:

```bash
git clone https://github.com/haanwoh/knullSU && cd knullSU
./bin/plx doctor
```

## A 60-second tour

```console
$ plx info
Google Pixel 7 · Android 15 · aarch64
device
  arch            aarch64
  selinux         enforcing
  verified boot   orange
  root present    no
pocketlinux
  rootfs          ~/.plx/rootfs/ubuntu   (Ubuntu 24.04 LTS · 1.6 GiB)
  engine          proot
  supervisor      running (pid 4127)

$ plx shell
root@pocketlinux:~# uname -a
Linux localhost 6.1.75-android14 #1 SMP PREEMPT aarch64 GNU/Linux

$ plx service up && plx service status
  pid            4127
  uptime         6s
services
service  state    pid   restarts  uptime  command
───────  ───────  ────  ────────  ──────  ──────────────────────────
sshd     running  4131  0         5s      /usr/sbin/sshd -D -e
web      running  4132  0         5s      python3 -m http.server 8000

$ plx hw battery
{
  "health": "GOOD",
  "percentage": 87,
  "plugged": "UNPLUGGED",
  "temperature": 31.4
}

$ plx backup create --compress zstd --prune 5
▸ snapshotting ubuntu → plx-ubuntu-20261110-120455.tar.zst
✓ wrote ~/.plx/backups/plx-ubuntu-20261110-120455.tar.zst (612.4 MiB)
```

## Command map

| command | what it does |
|---|---|
| `plx doctor` | pre-flight checks, each with the exact fix command |
| `plx info` | device + rootfs + engine + supervisor overview |
| `plx install [distro] [--list] [--url URL]` | provision a rootfs |
| `plx shell [-c CMD] [--engine proot\|chroot] [--dry-run]` | enter the guest |
| `plx exec <cmd…>` | one-shot command in the guest |
| `plx mount show` | inspect the bind-mount plan and the exact engine argv |
| `plx service up\|down\|ls\|status\|start\|stop\|restart\|logs\|reload` | supervise guest services |
| `plx recipe ls\|show\|apply\|copy` | declarative environments |
| `plx hw ls\|status\|<tool> [args]` | Termux:API hardware bridge |
| `plx backup create\|ls\|verify\|restore\|prune` | snapshots |
| `plx net ip\|ports\|ssh\|sshd-config\|doctor` | networking |
| `plx gui status\|start\|stop\|session` | optional desktop |
| `plx security report\|harden` | honest posture + hardening |
| `plx config show\|init\|set\|edit\|path` | configuration |

Every command supports `--json` (stable, scriptable), and every mutating command supports
`--dry-run`. Full reference: [docs/12-cli-reference.md](docs/12-cli-reference.md).

## Services in one file

`~/.plx/services.toml`:

```toml
[service.sshd]
command = "/usr/sbin/sshd -D -e"
restart = "always"          # always | on-failure | never
restart_delay = 2.0
max_restarts = 5
restart_window = 60

[service.web]
command = ["python3", "-m", "http.server", "8000", "--bind", "127.0.0.1"]
dir = "/root/projects"
restart = "on-failure"
env = { PYTHONUNBUFFERED = "1" }
```

```console
$ plx service up            # start plxd detached
$ plx service logs web -n 20
$ plx service down          # stops every child, cleanly
```

No systemd, no init hacks: each child gets its own session, output goes straight to
`~/.plx/logs/<name>.log`, and state is mirrored to JSON so `plx service status` still works
after the daemon dies. Boot-time start-up ships in [`scripts/termux-boot.sh`](scripts/termux-boot.sh)
(Termux:Boot).

## How it works

```
┌───────────────────────────── Android / Termux host ─────────────────────────────┐
│                                                                                 │
│  bin/plx ──► plx/cli.py ──► doctor · install · shell · service · recipe · hw  …  │
│                    │            │        │         │                           │
│                    │            │        │         └── plxd (UNIX socket)        │
│                    │            │        │               └── children → logs/    │
│                    │            │        └── proot -0 -r rootfs -b /dev … sh    │
│                    │            └── ~/.plx/rootfs/<distro>  (tar from mirrors)   │
│                    └── ~/.plx/{config.toml,services.toml,logs,state,backups}     │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

* **No daemon required** for shell/backup/hw — only `plxd` is long-lived, and only if you want it.
* **No writes outside** `~/.plx`, `~/.local/bin` and bind-mounted guest paths.
* **No `sudo`, no `/system`, no bootloader.**

## Project layout

```
bin/plx                  launcher (works from a checkout)
plx/cli.py               argument parsing + command handlers
plx/config.py            ~/.plx/config.toml (load / validate / TOML emit)
plx/device.py            getprop, arch, memory, storage, SELinux
plx/doctor.py            17 checks with fix hints
plx/rootfs.py            image registry, download, extract, post-configure
plx/mounts.py            bind planning, proot argv, chroot namespace script
plx/shell.py             engine selection + one-shot capture
plx/supervisor.py        service specs, save/load, socket client
plx/plxd.py              the supervisor daemon
plx/recipes.py           declarative environments
plx/hw.py                Termux:API bridge
plx/backup.py            snapshot / verify / restore / prune
plx/net.py               addresses, ports, SSH keys, sshd_config
plx/security.py          posture report + hardening
plx/gui.py               Termux:X11 session orchestration
examples/recipes/*.toml  devbox · datascience · webdev · minimal
examples/services/       sample services.toml
scripts/                 termux-boot.sh · completion.bash
tests/                   140+ tests, including a real daemon integration test
docs/                    architecture, operations, troubleshooting
```

## Development

```bash
python3 -m pip install -e '.[dev]'   # or: pip install pytest ruff
make test        # pytest
make lint        # ruff check + format check
make check       # both
make demo        # version + info + doctor --json, offline
```

The suite runs entirely against temporary `PLX_HOME` directories — it never touches a real
phone's rootfs or keys. `tests/test_supervisor.py` starts a real `plxd` subprocess and asserts
restart backoff, `gave up` state, clean shutdown and socket cleanup.

## Documentation

| doc | contents |
|---|---|
| [00 · Overview](docs/00-overview.md) | what this is, who it is for, design principles |
| [01 · Quickstart](docs/01-quickstart.md) | Termux setup, first rootfs, common pitfalls |
| [02 · Architecture](docs/02-architecture.md) | module map, data flow, why stdlib-only |
| [03 · Rootfs & engines](docs/03-rootfs-and-engines.md) | images, proot vs chroot, bind mounts |
| [04 · Hardware bridge](docs/04-hardware-bridge.md) | every Termux:API tool, permissions |
| [05 · Services](docs/05-services.md) | `plxd` semantics, restart policies, logs |
| [06 · Recipes](docs/06-recipes.md) | writing and applying environments |
| [07 · Networking](docs/07-networking.md) | SSH, keys, loopback vs LAN, tunnels |
| [08 · Desktop](docs/08-desktop.md) | Termux:X11, XFCE, VNC alternative |
| [09 · Security & limits](docs/09-security-and-limits.md) | threat model, what plx cannot do |
| [10 · Troubleshooting](docs/10-troubleshooting.md) | real failure modes and fixes |
| [11 · FAQ](docs/11-faq.md) | root? flashing? Play Store? battery? |
| [12 · CLI reference](docs/12-cli-reference.md) | every command, every flag |

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). The short version: keep it stdlib-only, add a test for
every behaviour you add, and anything that touches a device must be reversible with
`--dry-run` first. Security reports: [SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE). PocketLinux is for hardware **you own**. Using it to access a
device you do not control is illegal in most jurisdictions and is explicitly out of scope.
