# 02 · Architecture

## Shape of the code

```
plx/cli.py         argparse tree → handlers (small, return exit codes)
      │
      ├── config.py       ~/.plx/config.toml        (tomllib in, TOML out)
      ├── paths.py        single home dir, 0700     (PLX_HOME override)
      ├── console.py      human output + --json     (one flag, everywhere)
      ├── util.py         run/parse/format/hash     (no state)
      │
      ├── device.py       getprop, arch, memory, storage, SELinux
      ├── doctor.py       17 checks → pass/warn/fail/skip + fix strings
      │
      ├── rootfs.py       registry → download → extract → post_configure
      ├── mounts.py       Bind list → proot argv | chroot namespace script
      ├── shell.py        engine choice, preflight, exec, capture
      │
      ├── supervisor.py   ServiceSpec, TOML save/load, UNIX-socket client
      ├── plxd.py         the daemon: spawn, reap, backoff, state, socket
      │
      ├── recipes.py      Recipe TOML → ordered apply steps
      ├── hw.py           Termux:API tool registry + calls
      ├── backup.py       tar/verify/restore/prune + manifests
      ├── net.py          ips, ports, keys, sshd_config
      ├── security.py     findings, severity, hardening plan
      └── gui.py          Termux:X11 start/stop/session
```

No module imports another module's *state*; they exchange dataclasses and dicts. That is why the
whole suite can run offline against a temporary `PLX_HOME`.

## Data flow: `plx shell`

```
cli.cmd_shell
  └─ shell.enter(config, command, engine)
       ├─ shell._preflight      rootfs populated? engine binary present? shell present?
       ├─ mounts.proot_argv     proot -0 -r ROOT -w /root -b /dev -b /proc -b /sys \
       │                        -b $shared:/mnt/storage  /usr/bin/env -i HOME=… bash -lc CMD
       └─ subprocess.run(argv)  inherits the TTY; exit code propagates to your shell
```

`--dry-run` stops after `shlex.join(argv)`; `plx mount show --command` prints the same string
without touching a process.

## Data flow: `plxd`

```
plx service up ──(detached)──► python -m plx.plxd run
                                  │
   ~/.plx/services.toml ──────────┤ load ServiceSpec table
                                  ├─ bind UNIX socket (0600), write pid file
                                  ├─ start enabled services (own session, log file)
                                  └─ select() loop, 150 ms tick
                                       ├─ accept request → JSON reply
                                       ├─ reap dead children (poll)
                                       ├─ restart per policy: always | on-failure | never
                                       │    backoff = restart_delay
                                       │    give up after max_restarts in restart_window
                                       └─ mirror state to state/plxd.json (1/s)
```

Request protocol is one JSON object per line:

```json
{"cmd": "start", "name": "web"}
{"ok": true, "data": {"name": "web", "state": "running", "pid": 4132}}
```

Errors come back as `{"ok": false, "error": "unknown service 'ghost'"}` and the client raises
`SupervisorError` with that text — so `plx service start ghost` prints something useful.

## Why these choices

**Why proot and not `chroot` by default?** `chroot` needs `CAP_SYS_CHROOT`, i.e. root. `proot`
intercepts syscalls in userspace and fakes `uid 0`, which works on a stock, unrooted phone.
The trade-off is performance on syscall-heavy workloads (package installs, big compiles); the
`chroot` engine exists for rooted devices and is a single `--engine chroot` away.

**Why a custom supervisor instead of `runit`/`s6`?** They are excellent, but they assume a normal
filesystem and a writable service directory, and they add an install step inside a rootfs that
you may wipe tomorrow. `plxd` is 300 lines, lives in the host, logs to the host, and speaks JSON.

**Why not shell scripts?** Bash 5 is fine until you need to distinguish "process died with 1"
from "process was killed by signal", handle a TOML file, or serialise JSON. Python 3.11 is in
Termux's package repo and gives all of that with zero dependencies.

**Why `tar` and not `zstd` streams in Python?** `tar` is always present, handles sparse files,
hard links and ownership flags correctly, and is faster than anything we would write.

## Failure model

| component dies | consequence | recovery |
|---|---|---|
| `plxd` | children keep running (own sessions) but are unmanaged | `plx service up`; stale PID/socket files are cleaned on bind |
| a child crashes | restart per policy, bounded by `max_restarts`/`restart_window` | `plx service logs <name>`, then `plx service start <name>` |
| rootfs half-written | `plx install --force`, or `plx backup restore` | manifest hash catches truncated backups |
| phone reboots | nothing runs until `plx service up` (or Termux:Boot) | boot hook |
| disk full | installs/backups fail with the free-space number | `plx backup prune --keep 2` |

## Extension points

* **New engine** — implement `*_argv(config, command, …)` in `mounts.py` and add a branch to
  `engine_argv`; `shell.py` and the CLI need no change.
* **New hardware tool** — one row in `hw.TOOLS`.
* **New check** — one function in `doctor.py` returning a `Check`; add it to `run()`.
* **New command** — one handler in `cli.py` plus a subparser entry; keep it under 30 lines.
