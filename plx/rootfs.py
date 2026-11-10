"""Root filesystem provisioning.

``plx install`` has three front doors:

* **built-in images** — Ubuntu Base and Alpine minirootfs tarballs from their
  official mirrors, architecture-detected;
* **proot-distro** — reuse the rootfs proot-distro already knows how to build
  (the usual way to get Debian on a phone);
* **any tarball** — ``plx install --url https://…/rootfs.tar.gz``.

Extraction happens as your normal user with ``--no-same-owner``: the tarball's
uids are irrelevant because proot fakes ``root`` inside the guest, and nothing
in this project ever needs to chown the host.
"""

from __future__ import annotations

import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import __version__, console, device, paths, util
from .config import Config

#: Official, version-pinned rootfs tarballs.  Only architectures that the
#: upstream project actually publishes are listed.
IMAGES: dict[str, dict[str, str]] = {
    "ubuntu": {
        "aarch64": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/"
        "ubuntu-base-24.04.1-base-arm64.tar.gz",
        "x86_64": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/"
        "ubuntu-base-24.04.1-base-amd64.tar.gz",
        "armv7": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/"
        "ubuntu-base-24.04.1-base-armhf.tar.gz",
    },
    "alpine": {
        "aarch64": "https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/aarch64/"
        "alpine-minirootfs-3.20.3-aarch64.tar.gz",
        "x86_64": "https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/x86_64/"
        "alpine-minirootfs-3.20.3-x86_64.tar.gz",
        "armv7": "https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/armv7/"
        "alpine-minirootfs-3.20.3-armv7.tar.gz",
        "i686": "https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/x86/"
        "alpine-minirootfs-3.20.3-x86.tar.gz",
    },
}

#: Distributions only available through proot-distro.
PROOT_DISTRO_ONLY = ("debian", "kali", "archlinux", "void", "fedora", "opensuse")

MIN_FREE_BYTES = 1_500 * 1024 * 1024


class RootfsError(RuntimeError):
    """Raised when a rootfs cannot be created, found or removed safely."""


def distros() -> list[str]:
    return sorted({*IMAGES, *PROOT_DISTRO_ONLY})


def image_url(distro: str, arch: str | None = None) -> str | None:
    """Return the tarball URL for ``distro``/``arch`` (``None`` if unknown)."""
    table = IMAGES.get(distro)
    if not table:
        return None
    return table.get(arch or device.arch())


def supported_arches(distro: str) -> list[str]:
    return sorted(IMAGES.get(distro, {}))


def target_path(config: Config, dest: str | Path | None = None) -> Path:
    if dest:
        return Path(dest).expanduser()
    return config.rootfs


def proot_distro_rootfs(distro: str) -> Path:
    prefix = Path(os.environ.get("PREFIX", "/usr"))
    return prefix / "var/lib/proot-distro/installed-rootfs" / distro


def _download_curl(url: str, dest: Path) -> None:
    result = util.run(
        ["curl", "-fL", "--retry", "2", "--connect-timeout", "20", "-o", str(dest), url],
        timeout=1800,
    )
    if not result.ok:
        dest.unlink(missing_ok=True)
        raise RootfsError(f"download failed: {result.err.strip() or result.code}")


def _download_urllib(url: str, dest: Path) -> None:
    try:
        with urllib.request.urlopen(url, timeout=60) as response, open(dest, "wb") as handle:
            while True:
                block = response.read(1024 * 256)
                if not block:
                    break
                handle.write(block)
    except (urllib.error.URLError, OSError) as exc:
        dest.unlink(missing_ok=True)
        raise RootfsError(f"download failed: {exc}") from exc


def download(url: str, dest: Path, *, dry_run: bool = False) -> Path:
    """Download ``url`` to ``dest``, preferring curl when present."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        console.muted(f"[dry-run] curl -fL -o {dest} {url}")
        return dest
    console.step(f"downloading {url.rsplit('/', 1)[-1]}")
    started = time.monotonic()
    if util.have("curl"):
        _download_curl(url, dest)
    else:
        _download_urllib(url, dest)
    if not dest.exists() or dest.stat().st_size < 1024 * 512:
        dest.unlink(missing_ok=True)
        raise RootfsError("downloaded archive looks truncated or empty")
    console.muted(
        f"  {util.human_bytes(dest.stat().st_size)} in "
        f"{util.human_duration(time.monotonic() - started)}"
    )
    return dest


def extract(archive: Path, dest: Path, *, dry_run: bool = False) -> None:
    """Unpack a rootfs tarball into ``dest`` (auto-detects xz/gz)."""
    if not util.have("tar"):
        raise RootfsError("tar is required — run: pkg install tar")
    if dry_run:
        console.muted(f"[dry-run] tar -xf {archive} -C {dest} --no-same-owner")
        return
    dest.mkdir(parents=True, exist_ok=True)
    result = util.run(
        ["tar", "-xf", str(archive), "-C", str(dest), "--no-same-owner"], timeout=1800
    )
    if not result.ok:
        raise RootfsError(f"extraction failed: {result.err.strip() or result.code}")
    if not (dest / "etc").is_dir() or not (dest / "bin").exists():
        raise RootfsError(f"{dest} does not look like a Linux rootfs after extraction")


def read_os_release(rootfs: Path) -> dict[str, str]:
    return util.parse_kv(util.read_text(rootfs / "etc/os-release"))


def post_configure(config: Config, distro: str, rootfs: Path | None = None) -> list[str]:
    """Write the files that make a bare tarball usable inside proot."""
    root = rootfs or config.rootfs
    written: list[str] = []

    def write(relative: str, text: str, mode: int | None = None) -> None:
        target = root / relative.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        util.atomic_write(target, text, mode=mode)
        written.append(relative)

    write(
        "etc/resolv.conf",
        "# written by plx — public resolvers so DNS works inside the container\n"
        "nameserver 1.1.1.1\nnameserver 8.8.8.8\nnameserver 9.9.9.9\n",
    )
    write("etc/hostname", f"{config.core.hostname}\n")
    write(
        "etc/hosts",
        f"127.0.0.1 localhost\n::1 localhost ip6-localhost\n127.0.1.1 {config.core.hostname}\n",
    )
    write(
        "etc/plx-release",
        f"PLX_DISTRO={distro}\nPLX_VERSION={__version__}\nPLX_CREATED={util.now_iso()}\n"
        f"PLX_ENGINE={config.core.engine}\nPLX_HOST_MODEL={device.info().get('model', 'unknown')}\n",
    )
    write(
        "etc/profile.d/plx.sh",
        "# PocketLinux guest profile\n"
        "export PLX_GUEST=1\n"
        "export LANG=${LANG:-C.UTF-8}\n"
        f"export HOSTNAME={config.core.hostname}\n"
        "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
        "alias ll='ls -alF'\n"
        "alias ..='cd ..'\n"
        "[ -d /mnt/storage ] && cd /root 2>/dev/null || true\n",
    )
    if (root / "etc/apt").is_dir():
        write(
            "etc/apt/apt.conf.d/99-plx-sandbox",
            "// proot cannot setuid to _apt, so keep the apt sandbox user as root\n"
            'APT::Sandbox::User "root";\n'
            'Acquire::Languages "none";\n',
        )
    for directory in ("root/.ssh", "root/downloads", "root/projects", "mnt/storage"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    os.chmod(root / "root" / ".ssh", 0o700)
    return written


def install(
    config: Config,
    *,
    distro: str | None = None,
    arch: str | None = None,
    dest: str | Path | None = None,
    url: str | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Install a rootfs. Returns a summary dict (also used by ``--json``)."""
    name = (distro or config.core.distro).strip().lower()
    target = target_path(config, dest)
    arch = arch or device.arch()

    if target.exists() and any(target.iterdir()) and not dry_run:
        if not force:
            raise RootfsError(
                f"{target} already exists — pass --force to replace it, or use a different --dest"
            )
        shutil.rmtree(target)

    free = device.disk_free_for(target.parent if target.parent.exists() else Path.home())
    if free is not None and free < MIN_FREE_BYTES and not dry_run:
        raise RootfsError(
            f"only {util.human_bytes(free)} free — a rootfs needs ~1.5 GiB. "
            "Free space first or pick a smaller image (alpine)."
        )

    resolved_url = url
    method = "tarball"
    if resolved_url is None:
        resolved_url = image_url(name, arch)
        if resolved_url is None:
            method = "proot-distro"
            if name in PROOT_DISTRO_ONLY or name in IMAGES:
                if not util.have("proot-distro"):
                    hint = (
                        f"no built-in image for {name}/{arch}. Install proot-distro "
                        "(pkg install proot-distro) and re-run, or pass --url with a "
                        "rootfs tarball."
                    )
                    raise RootfsError(hint)
                return _install_via_proot_distro(name, target, dry_run=dry_run)
            raise RootfsError(
                f"unknown distribution {name!r}. Built-in: {', '.join(sorted(IMAGES))}; "
                f"proot-distro: {', '.join(PROOT_DISTRO_ONLY)}; or use --url."
            )

    archive = paths.cache_dir() / resolved_url.rsplit("/", 1)[-1]
    summary: dict[str, Any] = {
        "distro": name,
        "arch": arch,
        "rootfs": str(target),
        "url": resolved_url,
        "method": method,
        "dry_run": dry_run,
    }

    if dry_run:
        console.muted(f"[dry-run] would install {name} ({arch}) into {target}")
        download(resolved_url, archive, dry_run=True)
        extract(archive, target, dry_run=True)
        summary["files"] = []
        return summary

    download(resolved_url, archive)
    console.step(f"extracting into {target}")
    extract(archive, target)
    console.ok(f"rootfs ready at {target}")
    summary["files"] = post_configure(config, name, target)
    summary["size"] = directory_size(target)
    return summary


def _install_via_proot_distro(name: str, target: Path, *, dry_run: bool) -> dict[str, Any]:
    command = ["proot-distro", "install", name]
    if dry_run:
        console.muted(f"[dry-run] {' '.join(command)}")
        return {
            "distro": name,
            "rootfs": str(proot_distro_rootfs(name)),
            "method": "proot-distro",
            "dry_run": True,
        }
    console.step(f"proot-distro install {name} (this downloads a few hundred MB)")
    result = util.run(command, timeout=3600)
    if not result.ok:
        raise RootfsError(f"proot-distro failed: {result.err.strip() or result.code}")
    rootfs = proot_distro_rootfs(name)
    if not rootfs.exists():
        raise RootfsError(
            f"proot-distro reported success but {rootfs} is missing — check "
            "`proot-distro list` and pass --dest explicitly."
        )
    return {
        "distro": name,
        "rootfs": str(rootfs),
        "method": "proot-distro",
        "dry_run": False,
        "size": directory_size(rootfs),
        "note": "point config.core.rootfs at this path (plx install does this automatically)",
    }


def directory_size(path: Path) -> int | None:
    if not util.have("du"):
        return None
    result = util.run(["du", "-sk", str(path)], timeout=120)
    if not result.ok:
        return None
    try:
        return int(result.out.split()[0]) * 1024
    except (ValueError, IndexError):
        return None


def ensure(config: Config) -> Path:
    """Return the rootfs path or raise a helpful error."""
    root = config.rootfs
    if not root.exists() or not any(root.iterdir()):
        raise RootfsError(
            f"no rootfs at {root}\n"
            f"  install one:  plx install {config.core.distro}\n"
            "  list images:  plx install --list"
        )
    return root


def status(config: Config) -> dict[str, Any]:
    root = config.rootfs
    marker = util.parse_kv(util.read_text(root / "etc/plx-release"))
    os_release = read_os_release(root)
    shell = root / config.core.shell.lstrip("/")
    return {
        "rootfs": str(root),
        "exists": root.exists(),
        "populated": root.exists() and any(root.iterdir()) if root.exists() else False,
        "distro_name": os_release.get("PRETTY_NAME") or os_release.get("NAME") or "",
        "distro_id": os_release.get("ID", ""),
        "plx": marker,
        "shell": config.core.shell,
        "shell_present": shell.exists(),
        "size": directory_size(root) if root.exists() else None,
        "engine": config.core.engine,
        "free_space": device.disk_free_for(root.parent if root.parent.exists() else Path.home()),
    }


def remove(config: Config, *, confirm: bool = False, dry_run: bool = False) -> dict[str, Any]:
    """Delete the configured rootfs. Requires ``confirm=True``."""
    root = config.rootfs
    if not root.exists():
        return {"removed": False, "rootfs": str(root), "reason": "does not exist"}
    if root in (Path("/"), Path.home()) or len(root.parts) < 3:
        raise RootfsError(f"refusing to delete {root} — path looks unsafe")
    if not confirm:
        raise RootfsError("refusing to delete a rootfs without --yes")
    if dry_run:
        console.muted(f"[dry-run] rm -rf {root}")
        return {"removed": False, "rootfs": str(root), "dry_run": True}

    def onerror(func, path, _exc):  # noqa: ANN001 - shutil callback signature
        try:
            os.chmod(path, 0o700)
            func(path)
        except OSError:
            pass

    shutil.rmtree(root, onerror=onerror)
    return {"removed": True, "rootfs": str(root)}
