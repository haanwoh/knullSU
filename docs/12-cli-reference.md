# 12 · CLI reference

```
plx [--json] [-q] [--no-color] [--home DIR] <command> [args]
```

Global flags (accepted before or after the command name):

| flag | effect |
|---|---|
| `--json` | machine-readable output; errors become `{"ok": false, "error": "…"}` |
| `-q`, `--quiet` | suppress human output |
| `--no-color` | disable ANSI colours (also honoured: `NO_COLOR=1`, non-TTY stdout) |
| `--home DIR` | override `PLX_HOME` for this invocation |
| `--version` | print `plx <version>` |

Exit codes: `0` success · `1` runtime failure (or a failing `doctor` check) · `2` usage error /
invalid input · `124` timeout · `130` interrupted.

Environment: `PLX_HOME` (default `~/.plx`), `PLX_DEBUG=1` (tracebacks), `NO_COLOR`,
`PLX_FAKE_PROPS` (JSON, used by tests to simulate a device).

---

## `plx version`
`--json` → `{name, version, python, plx_home, platform}`.

## `plx info`
Device (getprop, arch, memory, SELinux, verified boot), rootfs state, engine availability,
supervisor status, config path.

## `plx doctor`
17 checks in fixed order, each `pass`/`warn`/`fail`/`skip` with a fix hint:

`python · host · arch · engine · proot · root · termux-api · storage · disk · memory · rootfs ·
services · daemon · network · tools · clock · config`

`--json` → `{plx_version, status, counts, checks[]}`. Exit code 1 if anything fails.

## `plx config`

| subcommand | notes |
|---|---|
| `show` | effective config (after defaults + validation) |
| `path` | prints the config file path |
| `init [--force]` | writes a default file |
| `set KEY VALUE` | `section.key`, e.g. `core.engine chroot`, `mounts.extra "/a:/b, /c:/d"` |
| `edit` | `$EDITOR`, then re-validates |

Known keys: `core.{engine,distro,rootfs,workdir,shell,hostname}`,
`mounts.{storage,extra}`, `net.{ssh_port,ssh_bind}`, `ui.color`,
`gui.{display,desktop}`.

## `plx install [distro]`
`--list` · `--arch` · `--dest` · `--url` · `--force` · `--dry-run` · `--json`

Persists `core.distro` (and `core.rootfs` when `--dest`/`proot-distro` is used).

## `plx rootfs`
`status` · `remove --yes [--dry-run]`

## `plx shell`
`-c/--command CMD` · `--engine proot|chroot` · `--root` (shortcut for `--engine chroot`) ·
`--no-login` · `--dry-run` · `--show` (explain the session, `--json` supported)

## `plx exec <command…>`
One-shot command in the guest, non-login. Same `--engine/--root/--dry-run` flags.

## `plx mount show`
Bind table + skipped sources. `--engine` · `--command` (also print the full argv) · `--json`.

## `plx service`

| subcommand | notes |
|---|---|
| `ls` | defined services + live state |
| `status` | daemon pid/uptime/socket + per-service table |
| `up` | start `plxd` detached, wait for the socket |
| `down` | graceful shutdown of daemon **and** children |
| `daemon` | run `plxd` in the foreground |
| `reload` | re-read `services.toml` (add/remove/stop as needed) |
| `example [--force]` | write a commented template |
| `edit` | `$EDITOR`, validate, reload |
| `start|stop|restart [NAME]` | one service (NAME optional when only one exists) |
| `logs NAME [-n LINES]` | tail of `~/.plx/logs/<name>.log` |

## `plx recipe`
`ls` · `show NAME` · `apply NAME [--dry-run] [--engine …] [--no-services] [--install-base]` ·
`copy NAME [--force]`

## `plx hw`
`ls` · `status` · `call TOOL [args…]` · `<tool> [args…]` (e.g. `plx hw battery`, `plx hw torch on`,
`plx hw clip "text"`). Tool flags go after `--`.

Tools: `battery · wifi · sensors · location · torch · clipboard-get · clipboard-set ·
notification · toast · vibrate · camera · tts · volume · brightness · wake-lock · wake-unlock ·
telephony · sms-list · share · open`

## `plx backup`
`create [--dest DIR] [--label L] [--compress auto|zstd|gzip|none] [--prune N] [--dry-run]` ·
`ls [--dest DIR]` · `verify ARCHIVE` · `restore ARCHIVE --yes [--skip-verify] [--dry-run]` ·
`prune --keep N [--dest DIR] [--dry-run]`

## `plx net`
`ip` · `ports` · `doctor` · `ssh [--force]` · `sshd-config [--password-auth] [--force]`

## `plx gui`
`status` · `start [--dry-run]` · `stop [--dry-run]` · `session [--desktop xfce|lxqt|mate|fluxbox|openbox|xterm] [--engine …]`

## `plx security`
`report` · `harden [--apply] [--dry-run]`

---

## Scripting examples

```bash
# fail a deployment if the phone is not ready
plx doctor --json | jq -e '.status != "fail"'

# take a snapshot only if the rootfs changed today
plx backup create --compress zstd --label nightly --prune 7

# restart the dev server when a build finishes
plx exec 'npm run build' && plx service restart devserver

# machine-readable hardware snapshot for a widget
plx hw status --json | jq '.data.battery.percentage'
```

## Shell completion

```bash
source scripts/completion.bash      # or copy to /usr/share/bash-completion/completions/plx
```
