# 10 · Troubleshooting

Start here, always:

```bash
plx doctor
plx doctor --json | head -40
PLX_DEBUG=1 plx <command>      # full traceback instead of a one-line error
```

## Installation

**`plx: command not found`**
`~/.local/bin` is not on `PATH`. Either `export PATH="$HOME/.local/bin:$PATH"`, or run
`./bin/plx` from the checkout.

**`python3: not found`**
`pkg install python`. PocketLinux needs 3.11+ (for `tomllib`); Termux ships 3.12.

**`proot: not found`**
`pkg install proot`. The doctor check tells you this before you hit it.

**`install` refuses: "already exists"**
Use `plx install <distro> --force` (wipes that rootfs) or `--dest` elsewhere. Your backups are
unaffected.

**Download fails or stalls**
The mirror may be blocked on your network. Copy the tarball manually into `~/.plx/cache/` with the
same file name and re-run `plx install` — it will reuse it. Or `plx install --url <mirror>`.

## Shell

**`plx shell` says "engine not available"**
`proot` missing (`pkg install proot`), or you asked for `--engine chroot` without `su`. Check
`plx shell --show`.

**Shell starts but there is no `/mnt/storage`**
`termux-setup-storage` once, restart Termux, then `plx mount show` — the bind is skipped silently
when the source does not exist.

**`apt update` fails: `Could not resolve 'deb.debian.org'`**
DNS inside the guest. Check `~/.plx/rootfs/<distro>/etc/resolv.conf` (should list 1.1.1.1).
`plx install --force` rewrites it. A VPN or private DNS on Android can also block it.

**`apt` prints `unsandboxed as root` warnings**
Known proot limitation; already mitigated by `etc/apt/apt.conf.d/99-plx-sandbox`
(`APT::Sandbox::User "root"`). Harmless.

**Commands die when I switch apps**
Android froze Termux. `termux-wake-lock` before long work, and add it to your boot hook.

**`Killed` during a big compile**
Out of memory (OOM killer). Use `make -j2` on 4 GB phones, and close other apps.

## Services

**`plxd is not running`**
`plx service up`. If it fails, read `~/.plx/logs/plxd.log` — usually a bad `services.toml`
(`plx service edit` validates) or a port already in use.

**`another plxd is already listening`**
A previous daemon is still alive: `plx service status`, then `plx service down`, or kill the PID
from `~/.plx/state/plxd.pid`.

**Service is `failed` with `gave up after N restarts`**
It crashed `max_restarts` times inside `restart_window`. Read `plx service logs <name>`; fix the
cause; `plx service start <name>` resets the counters.

**Service is `running` but does nothing**
Check `command` and `dir` in `services.toml`; a missing `dir` is ignored with a warning in
`plxd.log`. Remember commands run with the **host** environment (Termux paths), so point at guest
binaries explicitly (`/usr/sbin/sshd -D -e`).

**Logs are empty**
Some programs buffer when stdout is not a TTY. Set `PYTHONUNBUFFERED=1` (python), `-u`, or
`stdbuf -oL`.

## Backups

**`tar failed: file changed as we read it`**
Something wrote into the rootfs during the backup. Stop `plxd` (`plx service down`), retry, and
start it again. Exit code 1 from `tar` with a complete archive is still reported as a failure
here — deliberately strict.

**`not verified: hash mismatch`**
The archive changed on disk (partial copy, disk corruption). Do not restore it; use an older
snapshot.

**Restore filled the disk**
Restore keeps the previous rootfs as `*.pre-restore-*`. Delete it
(`plx rootfs remove` won't touch it — use `rm -rf`) or free space first.

## Hardware

**`termux-battery-status not found`**
`pkg install termux-api` **and** install the Termux:API app, then run it once and grant
permissions.

**A tool returns permission denied**
Android denied the permission. Open Android Settings → Apps → Termux:API → Permissions.

## Desktop

**Termux:X11 black screen**
`plx gui status` → is the server alive? Open the Termux:X11 app *after* `plx gui start`. If the
server died, `plx gui stop && plx gui start`.

**XFCE starts then exits immediately**
Missing `dbus-x11` in the guest: `plx exec 'apt install -y dbus-x11 xfce4 xfce4-terminal'`.

## Collecting a good bug report

```bash
plx version --json
plx doctor --json
plx info --json
plx service status --json
tail -50 ~/.plx/logs/plxd.log
```

Redact anything personal (IPs, SSIDs, hostnames) before pasting.
