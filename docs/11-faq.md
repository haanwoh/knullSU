# 11 · FAQ

**Does this root my phone?**
No. There is no exploit code in this project. PocketLinux runs *inside* Android as a normal app
and gives you a Linux userland, a supervisor and documented hardware access. See
[09 · Security & limits](09-security-and-limits.md).

**Can I flash it on a phone?**
No, and you would not want to: it is not a boot image or a ROM, it is a Python CLI that runs in
Termux. Nothing is written to `/system`, no bootloader is touched.

**Will it work on my phone?**
Almost certainly if it runs Android 9+ and Termux from F-Droid. `plx doctor` tells you in two
seconds. 32-bit-only devices need `alpine` (or a 32-bit tarball via `--url`).

**Does it need root?**
No. `proot` fakes `uid 0` in userspace. The `chroot` engine needs `su` and is optional, faster,
and the only way to get *real* read-only bind mounts.

**Is `proot` slow?**
For shell work, not noticeably. For `apt install` of hundreds of packages or a heavy compile,
expect 2-5×. That is the price of no root. Rooted devices should use `--engine chroot`.

**Why does it install a rootfs instead of using Termux packages?**
Isolation, reproducibility and `apt`/`apk`. A recipe rebuilds your environment exactly; Termux's
prefix is a single mutable space where one `pkg upgrade` can break everything.

**Can I run Docker?**
No. Docker needs kernel namespaces and cgroups control that Android does not give an app. You can
run `podman`-free containers with `proot`/`fakechroot`-style tools only in limited ways; PocketLinux
deliberately does not pretend otherwise.

**Can I run systemd?**
No, and you do not need it: `plxd` covers restart policies, logs and boot start-up. systemd
requires PID 1 and cgroup control.

**Where does my data live?**
`~/.plx` inside Termux's app sandbox: `rootfs/`, `backups/`, `logs/`, `state/`, plus two TOML
files. Uninstalling Termux deletes all of it — copy backups off-device first.

**How do I move everything to a new phone?**
`plx backup create`, copy `~/.plx/backups/*` and `~/.plx/*.toml` to the new phone, `plx install
<distro>`, `plx backup restore <archive> --yes`. Recipes make this even easier for the package
list.

**Can I use it over SSH from my laptop?**
Yes: `plx net ssh`, `plx net sshd-config`, `plx service start sshd`. Defaults to loopback + key
auth; read [07 · Networking](07-networking.md) before exposing it to the LAN.

**Does it work without Termux:API?**
Yes. You lose `plx hw` (battery, sensors, torch, clipboard, notifications) and nothing else.

**Is there a GUI?**
Optional: Termux:X11 + XFCE via `plx gui`. Most users are better served by SSH port-forwarding
JupyterLab or a code server — see [08 · Desktop](08-desktop.md).

**Can it survive a reboot?**
Services can, via `scripts/termux-boot.sh` + the Termux:Boot app. The rootfs and config obviously
persist.

**How do I completely remove it?**
```bash
plx service down
rm -rf ~/.plx ~/.local/bin/plx
```
and delete the Termux packages you no longer want (`pkg uninstall proot`).

**Why "PocketLinux" and not "knullSU"?**
`knullSU` is the repository name; `pocketlinux` is the Python package and the project you actually
use (`plx` on the command line).

**Does it phone home?**
No telemetry, no analytics, no network access unless you ask for it (install, package managers,
hardware tools that use the network). Everything is stdlib and auditable in an afternoon.

**How can I help?**
Reproduce a bug with `PLX_DEBUG=1`, add a test that fails, then fix it — see
[CONTRIBUTING.md](../CONTRIBUTING.md).
