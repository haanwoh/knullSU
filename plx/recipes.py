"""Recipes — declarative, reproducible guest environments.

A recipe is one TOML file describing packages, services, hooks and suggested
mounts.  Apply it and you get the same devbox (or datascience stack) on any
phone, months later, without remembering which ``apt install`` you ran.

Example (``examples/recipes/devbox.toml``)::

    [recipe]
    name = "devbox"
    description = "git, compilers, python, node"
    base = "ubuntu"

    [packages]
    apt = ["git", "build-essential", "python3-pip"]
    npm = ["typescript"]

    [hooks]
    post_install = ["git config --global init.defaultBranch main"]

    [services.web]
    command = "python3 -m http.server 8000"
    restart = "on-failure"
"""

from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import console, paths, rootfs, shell, supervisor
from .config import Config

APK_ONLY = "apk"
APT_ONLY = "apt"
PACKAGE_MANAGERS = (APT_ONLY, APK_ONLY)


class RecipeError(ValueError):
    """Raised for an invalid or inapplicable recipe."""


@dataclass(slots=True)
class Recipe:
    name: str
    path: Path
    description: str = ""
    base: str = ""
    env: dict[str, str] = field(default_factory=dict)
    mounts: list[str] = field(default_factory=list)
    packages: dict[str, list[str]] = field(default_factory=dict)
    services: dict[str, supervisor.ServiceSpec] = field(default_factory=dict)
    hooks: dict[str, list[str]] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "description": self.description,
            "base": self.base,
            "env": self.env,
            "mounts": self.mounts,
            "packages": self.packages,
            "services": {name: spec.to_dict() for name, spec in self.services.items()},
            "hooks": self.hooks,
            "notes": self.notes,
        }

    def summary_rows(self) -> list[str]:
        bits = []
        for manager, items in self.packages.items():
            if items:
                bits.append(f"{manager}: {len(items)}")
        if self.services:
            bits.append(f"services: {len(self.services)}")
        return bits


def _as_list(value: Any, what: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    raise RecipeError(f"{what}: expected a string or list of strings")


def load(path: Path | str) -> Recipe:
    target = Path(path).expanduser()
    if not target.exists():
        raise RecipeError(f"recipe not found: {target}")
    try:
        with open(target, "rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise RecipeError(f"{target}: invalid TOML — {exc}") from exc

    meta = data.get("recipe", {})
    if not isinstance(meta, dict):
        raise RecipeError(f"{target}: [recipe] must be a table")

    name = str(meta.get("name") or target.stem)
    packages_raw = data.get("packages", {})
    if not isinstance(packages_raw, dict):
        raise RecipeError(f"{target}: [packages] must be a table")
    packages = {
        str(manager): _as_list(items, f"packages.{manager}")
        for manager, items in packages_raw.items()
    }
    hooks_raw = data.get("hooks", {})
    if not isinstance(hooks_raw, dict):
        raise RecipeError(f"{target}: [hooks] must be a table")
    hooks = {str(key): _as_list(value, f"hooks.{key}") for key, value in hooks_raw.items()}

    env_raw = data.get("env", {})
    if not isinstance(env_raw, dict):
        raise RecipeError(f"{target}: [env] must be a table")
    env = {str(key): str(value) for key, value in env_raw.items()}

    mounts_raw = data.get("mounts", {})
    mounts: list[str] = []
    if isinstance(mounts_raw, dict):
        mounts = _as_list(mounts_raw.get("extra"), "mounts.extra")
    elif isinstance(mounts_raw, list):
        mounts = _as_list(mounts_raw, "mounts")

    services: dict[str, supervisor.ServiceSpec] = {}
    services_raw = data.get("services", data.get("service", {}))
    if services_raw:
        try:
            services = supervisor.parse_services({"service": services_raw})
        except supervisor.ServiceError as exc:
            raise RecipeError(f"{target}: {exc}") from exc

    return Recipe(
        name=name,
        path=target,
        description=str(meta.get("description", "")),
        base=str(meta.get("base", "")),
        env=env,
        mounts=mounts,
        packages=packages,
        services=services,
        hooks=hooks,
        notes=str(meta.get("notes", "")),
    )


def recipe_dirs() -> list[Path]:
    bundled = Path(__file__).resolve().parent.parent / "examples" / "recipes"
    return [bundled, paths.recipes_dir()]


def discover() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for directory in recipe_dirs():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.toml")):
            try:
                recipe = load(path)
            except RecipeError:
                continue
            found[recipe.name] = path
    return found


def resolve(name_or_path: str) -> Path:
    candidate = Path(name_or_path).expanduser()
    if candidate.suffix == ".toml" and candidate.exists():
        return candidate
    catalog = discover()
    if name_or_path in catalog:
        return catalog[name_or_path]
    if candidate.exists():
        return candidate
    raise RecipeError(
        f"no recipe named {name_or_path!r} — available: {', '.join(sorted(catalog)) or 'none'}"
    )


def detect_package_manager(config: Config) -> str | None:
    root = config.rootfs
    if (root / "usr/bin/apt-get").exists() or (root / "bin/apt-get").exists():
        return APT_ONLY
    if (root / "sbin/apk").exists() or (root / "usr/sbin/apk").exists():
        return APK_ONLY
    return None


def _step(name: str, ok: bool, detail: str = "", output: str = "") -> dict[str, Any]:
    return {"step": name, "ok": ok, "detail": detail, "output": output[-4000:]}


def apply(
    recipe: Recipe,
    config: Config,
    *,
    dry_run: bool = False,
    engine: str | None = None,
    with_services: bool = True,
    install_base: bool = False,
) -> dict[str, Any]:
    """Apply a recipe to the guest. Returns a step-by-step report."""
    steps: list[dict[str, Any]] = []
    suggestions: list[str] = []

    if not config.rootfs.exists() or not any(config.rootfs.iterdir()):
        if recipe.base and install_base:
            steps.append(_step("install-base", False, f"installing {recipe.base} …"))
            summary = rootfs.install(config, distro=recipe.base, dry_run=dry_run)
            steps[-1].update(
                _step("install-base", True, f"{recipe.base} → {summary.get('rootfs')}")
            )
        else:
            raise RecipeError(
                f"no rootfs at {config.rootfs} — run: plx install {recipe.base or config.core.distro}, "
                "or add --install-base"
            )

    manager = detect_package_manager(config)
    if manager is None and not dry_run:
        steps.append(_step("detect", False, "no apt-get or apk inside the rootfs"))
        raise RecipeError("cannot detect a package manager inside the guest")

    for kind in ("pre_install",):
        for command in recipe.hooks.get(kind, []):
            steps.append(_run_hook(config, kind, command, engine, dry_run))

    # -- system packages --------------------------------------------------
    system_packages = recipe.packages.get(manager or APT_ONLY, [])
    if system_packages and manager:
        if manager == APT_ONLY:
            commands = [
                ("apt-update", "apt-get update -qq"),
                (
                    "apt-install",
                    "DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "
                    + " ".join(system_packages),
                ),
            ]
        else:
            commands = [("apk-install", "apk add --no-cache " + " ".join(system_packages))]
        for label, command in commands:
            steps.append(_run_command(config, label, command, engine, dry_run))

    other_managers = [
        name for name in recipe.packages if name not in PACKAGE_MANAGERS and recipe.packages[name]
    ]
    if other_managers:
        suggestions.append(
            "recipe also declares packages for: " + ", ".join(sorted(other_managers))
        )

    if recipe.packages.get("pip"):
        packages = " ".join(recipe.packages["pip"])
        steps.append(
            _run_command(
                config,
                "pip",
                f"python3 -m pip install --no-input --break-system-packages {packages}",
                engine,
                dry_run,
            )
        )
        if not steps[-1]["ok"] and not dry_run:
            steps.append(
                _run_command(
                    config,
                    "pip-retry",
                    f"python3 -m pip install --no-input {packages}",
                    engine,
                    dry_run,
                )
            )

    if recipe.packages.get("npm"):
        packages = " ".join(recipe.packages["npm"])
        steps.append(_run_command(config, "npm", f"npm install -g {packages}", engine, dry_run))

    for command in recipe.hooks.get("post_install", []):
        steps.append(_run_hook(config, "post_install", command, engine, dry_run))

    # -- services ---------------------------------------------------------
    services_added: list[str] = []
    if recipe.services and with_services:
        if dry_run:
            services_added = sorted(recipe.services)
            steps.append(
                _step("services", True, f"[dry-run] would add {', '.join(services_added)}")
            )
        else:
            try:
                existing = supervisor.load_services()
            except supervisor.ServiceError as exc:
                raise RecipeError(f"cannot read services.toml: {exc}") from exc
            for name, spec in recipe.services.items():
                existing[name] = spec
                services_added.append(name)
            target = supervisor.save_services(existing)
            steps.append(_step("services", True, f"wrote {target} (+{len(services_added)})"))
            if services_added and supervisor.ping():
                try:
                    supervisor.SupervisorClient().reload()
                    steps.append(_step("services-reload", True, "plxd reloaded"))
                except supervisor.SupervisorError as exc:
                    steps.append(_step("services-reload", False, str(exc)))

    for mount in recipe.mounts:
        suggestions.append(f'plx config set mounts.extra "{mount}"')
    for key, value in recipe.env.items():
        suggestions.append(f"export {key}={value}   (inside the guest, or add to hooks)")

    ok = all(step["ok"] for step in steps)
    return {
        "recipe": recipe.name,
        "path": str(recipe.path),
        "dry_run": dry_run,
        "ok": ok,
        "steps": steps,
        "services_added": services_added,
        "suggestions": suggestions,
        "package_manager": manager,
    }


def _run_command(
    config: Config, label: str, command: str, engine: str | None, dry_run: bool
) -> dict[str, Any]:
    if dry_run:
        console.muted(f"[dry-run] {label}: {command}")
        return _step(label, True, f"[dry-run] {command}")
    console.step(f"{label}: {command[:70]}")
    try:
        result = shell.capture(config, command, engine=engine, timeout=7200)
    except shell.ShellError as exc:
        return _step(label, False, str(exc))
    detail = "ok" if result.ok else f"exit {result.code}"
    if not result.ok:
        detail = (result.err.strip() or result.out.strip() or detail)[-300:]
    return _step(label, result.ok, detail, result.out + result.err)


def _run_hook(
    config: Config, kind: str, command: str, engine: str | None, dry_run: bool
) -> dict[str, Any]:
    return _run_command(config, f"hook:{kind}", command, engine, dry_run)


def copy_into_user_dir(path: Path, *, force: bool = False) -> Path:
    """Copy a bundled recipe into ``~/.plx/recipes`` for local editing."""
    target = paths.recipes_dir() / path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        return target
    shutil.copyfile(path, target)
    return target


def render(recipe: Recipe) -> None:
    console.kv_block(
        {
            "name": recipe.name,
            "description": recipe.description or "-",
            "base": recipe.base or "(current rootfs)",
            "packages": ", ".join(
                f"{manager}×{len(items)}" for manager, items in recipe.packages.items() if items
            )
            or "-",
            "services": ", ".join(recipe.services) or "-",
            "hooks": ", ".join(f"{kind}×{len(items)}" for kind, items in recipe.hooks.items())
            or "-",
            "path": str(recipe.path),
        }
    )
    if recipe.notes:
        console.out()
        console.out(recipe.notes.strip())


def render_report(report: dict[str, Any]) -> None:
    rows = [
        [
            console.paint("✓" if step["ok"] else "✗", "green" if step["ok"] else "red"),
            step["step"],
            step["detail"][:80],
        ]
        for step in report["steps"]
    ]
    console.table(["", "step", "result"], rows)
    if report["services_added"]:
        console.out()
        console.ok("services available: " + ", ".join(report["services_added"]))
        console.muted("  start them with: plx service start <name>")
    if report["suggestions"]:
        console.out()
        console.out(console.paint("optional follow-ups", "bold"))
        console.bullet_list(report["suggestions"])
