# 08 · Desktop (optional)

PocketLinux is shell-first. If you want a real X session on the phone screen (or a tablet, or a
TV stick), `plx gui` orchestrates Termux:X11 for you.

## Install

```bash
pkg install x11-repo
pkg install termux-x11-nightly
# plus the "Termux:X11" app from F-Droid
```

Inside the guest, a desktop environment:

```bash
plx recipe apply devbox                 # ubuntu base with a working toolchain
plx exec 'apt install -y xfce4 xfce4-terminal dbus-x11'
```

## Run

```bash
plx gui start          # Termux:X11 server on :0 (records the PID in ~/.plx/state/gui.json)
plx gui session        # foreground XFCE session inside the rootfs
plx gui status
plx gui stop
```

Open the Termux:X11 app *after* `plx gui start` (the app connects to the running server). If it
shows a black screen, `plx gui status` tells you whether the server process is alive.

Supported session names for `--desktop`:

| name | command run inside the guest |
|---|---|
| `xfce` (default) | `dbus-run-session -- startxfce4` |
| `lxqt` | `dbus-run-session -- startlxqt` |
| `mate` | `dbus-run-session -- mate-session` |
| `fluxbox` | `dbus-run-session -- fluxbox` |
| `openbox` | `dbus-run-session -- openbox-session` |
| `xterm` | `xterm` (no desktop, just a terminal) |

```bash
plx gui session --desktop lxqt
plx config set gui.desktop lxqt
```

The display can be changed too (`plx config set gui.display :1`) if you run several.

## Why this is a separate module

A desktop drags in a compositor, a session bus, fonts and a window manager — hundreds of
megabytes and plenty of failure modes that have nothing to do with a usable Linux shell. Keeping
it optional means `plx shell`, `plx service` and `plx backup` stay fast and dependency-free.

## Alternatives

* **VNC inside the guest** — `apt install tigervnc-standalone-server`, then `vncserver :1` and
  connect from any VNC client. Works without Termux:X11, slightly laggy.
* **Code server / JupyterLab in the browser** — no X at all:
  `plx recipe apply datascience`, `plx service start jupyter`, then SSH-forward 8888.
* **Termux's own X11** — `pkg install x11-repo termux-x11-nightly` and run `termux-x11 :1 &`
  manually; `plx gui` is just a supervised, stateful wrapper around that.

## Practical notes

* Battery: a full XFCE session keeps the GPU awake. Hold `termux-wake-lock` or Android will freeze
  the app when the screen turns off — and that will look like "X11 crashed".
* Keyboard: any Bluetooth/USB keyboard works; Termux's extra-keys row is enough for `tmux`.
* Resolution: set it in the Termux:X11 app preferences, not in `plx`.
