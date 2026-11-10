# 07 · Networking

## Addresses and ports

```console
$ plx net ip
  hostname   localhost
  addresses  ['192.168.1.42']

$ plx net ports
port   proto  address  exposed
─────  ─────  ───────  ───────
8022   tcp    127.0.0.1  no
8000   tcp    127.0.0.1  no
```

`exposed` means "listening on all interfaces" (`0.0.0.0`, `::`, `*`) — i.e. reachable from your
Wi-Fi. `plx security report` counts those.

## SSH into your own phone

```bash
plx net ssh            # ed25519 key at ~/.plx/rootfs/<distro>/root/.ssh/id_ed25519
plx net sshd-config    # loopback-only, key-only, no root password login
plx recipe apply minimal   # includes openssh-server (Alpine)
plx service start sshd
```

```console
$ plx net ssh
  user       root
  port       8022
  bind       127.0.0.1 (loopback only)
  from host  ssh -p 8022 root@192.168.1.42
  key        ~/.plx/rootfs/ubuntu/root/.ssh/id_ed25519
```

Then, from a laptop on the same Wi-Fi:

```bash
ssh -i ~/phone-key -p 8022 root@192.168.1.42
```

### Reaching a loopback-only guest service

Port-forward through SSH instead of binding services to the LAN:

```bash
# on the laptop: forward local 8888 → the phone's guest-localhost:8888
ssh -p 8022 -L 8888:127.0.0.1:8888 root@192.168.1.42
# then open http://localhost:8888 for JupyterLab
```

For this, the guest `sshd` must be reachable from the LAN, so set:

```bash
plx config set net.ssh_bind 0.0.0.0
plx net sshd-config
plx service restart sshd
```

**Read this before you do that:** an `sshd` on `0.0.0.0` is visible to every device on the
network (café Wi-Fi included). PocketLinux defaults to loopback and key-only for that reason.
`plx security report` will flag it as a medium finding, every time.

### Termux-level SSH (host, not guest)

If you only need a shell in Termux itself, Termux's own `sshd` is enough:

```bash
pkg install openssh
sshd                       # listens on 8022 by default
whoami                     # your Termux user, e.g. u0_a123
```

Guest `sshd` and host `sshd` are different worlds: the guest one lands you in the rootfs, the
host one in Termux. Do not run both on the same port — `plx net doctor` tells you if it is taken.

## DNS inside the guest

proot cannot reach Android's resolver socket, so `plx install` writes public resolvers:

```
nameserver 1.1.1.1
nameserver 8.8.8.8
nameserver 9.9.9.9
```

If your network blocks them, edit `~/.plx/rootfs/<distro>/etc/resolv.conf` and use your router's
address. `plx install --force` rewrites the file.

## Connectivity checks

```bash
plx doctor                      # includes an outbound TCP probe
plx net doctor                  # hostname, addresses, ssh port state, sshd presence
plx exec ping -c1 1.1.1.1       # if iputils-ping is installed in the guest
```

Android sometimes routes mobile data through a NAT that breaks ICMP; a TCP probe (what `doctor`
does) is the more reliable signal.

## Ports used by PocketLinux

| port | owner | default bind |
|---|---|---|
| 8022 | guest `sshd` (configurable) | 127.0.0.1 |
| 8022 | Termux host `sshd` | 0.0.0.0 (Termux default) |
| 8000 | example `web` service | 127.0.0.1 |
| 8888 | example `jupyter` service | 127.0.0.1 |

Change the guest port with `plx config set net.ssh_port 2222`.
