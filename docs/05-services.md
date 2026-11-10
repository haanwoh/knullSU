# 05 · Services (`plxd`)

Termux has no init system. `plxd` fills that gap for the things you actually want running:
an `sshd`, a dev server, a notebook, a sync loop.

## Lifecycle

```bash
plx service example     # commented template → ~/.plx/services.toml
plx service edit        # $EDITOR, validates, reloads a running daemon
plx service up          # start plxd detached
plx service status
plx service logs web -n 50
plx service restart web
plx service down        # stop all children, remove socket/pid
plx service daemon      # foreground (systemd-style, for debugging)
```

`plx service up` spawns `python -m plx.plxd run` in its own session, redirects its output to
`~/.plx/logs/plxd.log`, and waits (up to 10 s) for the control socket before returning.

## Definition format

```toml
[service.web]
command = ["python3", "-m", "http.server", "8000", "--bind", "127.0.0.1"]
dir = "/root/projects"          # working directory (missing → ignored with a warning)
env = { PYTHONUNBUFFERED = "1" }
restart = "on-failure"          # always | on-failure | never
restart_delay = 2.0             # seconds before the next attempt
max_restarts = 5                # inside restart_window…
restart_window = 60.0           # …before the service is marked failed
stop_timeout = 10.0             # SIGTERM → SIGKILL grace period
stop_signal = "TERM"            # TERM | INT | HUP | QUIT | KILL
enabled = true                  # false = defined but never auto-started
description = "static file server"
```

`command` may be a string (split with `shlex`) or an array (preferred: no quoting bugs).

## Restart semantics

| policy | exits 0 | exits non-zero | killed by signal |
|---|---|---|---|
| `never` | stopped | failed | failed |
| `on-failure` | stopped | restart | restart |
| `always` | restart | restart | restart |

Restarts are counted per sliding window: with `max_restarts = 5` and `restart_window = 60`,
six crashes inside a minute put the service in `failed` with
`gave up after 5 restarts in 60s` in the log. Fix the cause, then `plx service start <name>`
(which resets the counters) or `plx service reload`.

## Process hygiene

* every child gets `start_new_session=True`, so it is **not** killed when your shell exits;
* stop signals go to the whole process group (`os.killpg`), so a shell script's children die too;
* stdout and stderr are the same file (`logs/<name>.log`), rotated at 5 MiB to `.log.1`;
* `plxd` writes `state/plxd.json` about once a second: `plx service status` still works after a
  daemon crash, and scripts can read it without a socket.

## Control protocol

`state/plxd.sock`, mode `0600`, one JSON object per line:

| request | reply |
|---|---|
| `{"cmd":"status"}` | daemon info + all service states |
| `{"cmd":"start","name":"web"}` | the service's new state |
| `{"cmd":"stop","name":"web"}` | same |
| `{"cmd":"restart","name":"web"}` | same |
| `{"cmd":"reload"}` | `{"added":[…],"removed":[…]}` |
| `{"cmd":"logs","name":"web","lines":50}` | tail of the log |
| `{"cmd":"shutdown"}` | graceful stop of everything |

Anything you can do with the CLI you can do from a script:

```python
from plx import supervisor
client = supervisor.SupervisorClient()
if client.status()["services"]["web"]["state"] != "running":
    client.start("web")
```

## Boot start-up

With the **Termux:Boot** app:

```bash
mkdir -p ~/.termux/boot
cp scripts/termux-boot.sh ~/.termux/boot/plx-boot.sh
chmod +x ~/.termux/boot/plx-boot.sh
```

The hook waits for shared storage (it appears late on some devices), takes a wake lock, then runs
`plx service up`. Logs land in `~/.plx/logs/boot.log`.

## Guest `sshd`

```bash
plx recipe apply minimal        # alpine + openssh-server
plx net ssh                     # generate a key, print the ssh command
plx net sshd-config             # loopback-only, key-only
plx service start sshd
```

`sshd` must exist *inside* the rootfs (`apt install openssh-server` / `apk add openssh`); the
host's Termux `sshd` is a different binary. See [07 · Networking](07-networking.md) for exposing
it beyond loopback — and read the warning there.
