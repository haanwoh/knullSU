"""The ``plx`` command line interface.

Design rules for this module:

* every handler is small and returns an exit code;
* human output and ``--json`` output are produced from the same data;
* nothing mutates the host without either ``--yes`` or an explicit flag;
* errors are one line plus the exact command that fixes them.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import (
    __version__,
    backup,
    console,
    device,
    doctor,
    gui,
    hw,
    mounts,
    net,
    paths,
    recipes,
    rootfs,
    security,
    shell,
    supervisor,
    util,
)
from . import (
    config as config_mod,
)
from . import plxd as plxd_mod

Handler = Callable[[argparse.Namespace], int]

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _load_config(args: argparse.Namespace) -> config_mod.Config:
    cfg = config_mod.load()
    if cfg.warnings and not console.json_mode() and not console.quiet():
        for warning in cfg.warnings:
            console.warn(f"config: {warning}")
    return cfg


def _emit_json(payload: Any) -> None:
    console.json_out(payload)


def _finish_json(payload: dict[str, Any]) -> int:
    _emit_json(payload)
    return EXIT_OK


def _need_rootfs(cfg: config_mod.Config) -> bool:
    try:
        rootfs.ensure(cfg)
    except rootfs.RootfsError as exc:
        console.err(str(exc))
        return False
    return True


# --------------------------------------------------------------------------
# version / info / doctor
# --------------------------------------------------------------------------
def cmd_version(args: argparse.Namespace) -> int:
    payload = {
        "name": "pocketlinux",
        "version": __version__,
        "python": ".".join(map(str, sys.version_info[:3])),
        "plx_home": str(paths.home()),
        "platform": sys.platform,
    }
    if console.json_mode():
        return _finish_json(payload)
    console.out(f"{console.paint('plx', 'bold')} {__version__}")
    console.muted(f"python {payload['python']} · {payload['platform']} · {payload['plx_home']}")
    return EXIT_OK


def cmd_info(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    data = device.info()
    payload = {
        "device": data,
        "rootfs": rootfs.status(cfg),
        "engines": shell.available_engines(),
        "daemon": {"running": supervisor.ping(), "pid": supervisor.alive_pid()},
        "config": str(cfg.source or paths.config_file()),
    }
    if console.json_mode():
        return _finish_json(payload)

    console.out(console.paint(device.summary_line(), "bold"))
    console.header("device")
    console.kv_block(
        {
            "android": data.get("android", "-"),
            "sdk": data.get("sdk", "-"),
            "abi": data.get("abi", "-"),
            "arch": data.get("arch"),
            "kernel": data.get("kernel"),
            "selinux": data.get("selinux"),
            "verified boot": data.get("verified_boot", "-"),
            "security patch": data.get("security_patch", "-"),
            "root present": "yes" if data.get("root_present") else "no",
            "termux": data.get("termux_version") or "no",
            "memory": util.human_bytes(data.get("memory_total"))
            if data.get("memory_total")
            else "?",
            "cpus": data.get("cpus"),
        }
    )
    console.header("pocketlinux")
    state = payload["rootfs"]
    console.kv_block(
        {
            "plx version": data.get("plx_version"),
            "home": data.get("plx_home"),
            "rootfs": state["rootfs"],
            "rootfs ready": "yes" if state["populated"] else "no",
            "distro": state["distro_name"] or cfg.core.distro,
            "rootfs size": util.human_bytes(state["size"]) if state.get("size") else "?",
            "engine": cfg.core.engine,
            "proot": "yes" if payload["engines"]["proot"]["available"] else "no",
            "chroot (su)": "yes" if payload["engines"]["chroot"]["available"] else "no",
            "supervisor": f"running (pid {payload['daemon']['pid']})"
            if payload["daemon"]["running"]
            else "stopped",
        }
    )
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    checks = doctor.run(cfg)
    summary = doctor.summarize(checks)
    if console.json_mode():
        _emit_json(summary)
        return doctor.exit_code(summary)
    console.out(console.paint("PocketLinux self-check", "bold"))
    doctor.render(checks)
    console.out()
    counts = summary["counts"]
    console.out(
        f"{counts['pass']} ok · {counts['warn']} warnings · {counts['fail']} failing · "
        f"{counts['skip']} skipped"
    )
    return doctor.exit_code(summary)


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------
def cmd_config(args: argparse.Namespace) -> int:
    action = args.action
    if action == "path":
        if console.json_mode():
            return _finish_json({"config": str(paths.config_file()), "home": str(paths.home())})
        console.out(str(paths.config_file()))
        return EXIT_OK
    if action == "init":
        target, written = config_mod.init(force=args.force)
        if console.json_mode():
            return _finish_json({"path": str(target), "written": written})
        if written:
            console.ok(f"wrote {target}")
        else:
            console.info(f"{target} already exists — use --force to overwrite")
        return EXIT_OK
    if action == "show":
        cfg = _load_config(args)
        if console.json_mode():
            return _finish_json({"path": str(cfg.source), "config": cfg.to_dict()})
        console.kv_block({"file": str(cfg.source)})
        for section, values in cfg.to_dict().items():
            console.header(section)
            console.kv_block(values)
        return EXIT_OK
    if action == "set":
        cfg = _load_config(args)
        updated = config_mod.set_value(cfg, args.key, args.value)
        target = config_mod.save(updated)
        if console.json_mode():
            return _finish_json({"path": str(target), "key": args.key, "value": args.value})
        console.ok(f"{args.key} = {args.value}  ({target})")
        return EXIT_OK
    if action == "edit":
        target = paths.config_file()
        if not target.exists():
            config_mod.init()
        editor = os.environ.get("EDITOR") or util.which("nano") or util.which("vi") or "vi"
        subprocess.run([editor, str(target)], check=False)
        try:
            cfg = config_mod.load()
        except config_mod.ConfigError as exc:
            console.err(str(exc))
            return EXIT_FAIL
        console.ok(f"config ok ({len(cfg.warnings)} warning(s))")
        return EXIT_OK
    console.err(f"unknown config action {action!r}")
    return EXIT_USAGE


# --------------------------------------------------------------------------
# install / rootfs
# --------------------------------------------------------------------------
def cmd_install(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    if args.list:
        rows = []
        for name in rootfs.distros():
            arches = rootfs.supported_arches(name)
            method = "tarball" if arches else "proot-distro"
            installed = paths.rootfs_path(name).exists() and any(paths.rootfs_path(name).iterdir())
            rows.append([name, ", ".join(arches) or "all", method, "yes" if installed else ""])
        if console.json_mode():
            return _finish_json(
                {
                    "distros": [
                        {
                            "name": row[0],
                            "arches": row[1],
                            "method": row[2],
                            "installed": bool(row[3]),
                        }
                        for row in rows
                    ],
                    "current_arch": device.arch(),
                    "builtin_images": sorted(rootfs.IMAGES),
                }
            )
        console.table(["distro", "architectures", "method", "installed"], rows)
        console.muted(f"\ndetected architecture: {device.arch()}")
        console.muted("install: plx install <distro>   |   custom: plx install --url <tarball>")
        return EXIT_OK

    summary = rootfs.install(
        cfg,
        distro=args.distro,
        arch=args.arch,
        dest=args.dest,
        url=args.url,
        force=args.force,
        dry_run=args.dry_run,
    )

    installed_path = Path(summary["rootfs"])
    overrides: dict[str, Any] = {}
    if args.distro:
        overrides["distro"] = summary.get("distro", args.distro)
    if args.dest or summary.get("method") == "proot-distro":
        overrides["rootfs"] = str(installed_path)
    if overrides and not args.dry_run:
        config_mod.save(cfg.with_overrides(**overrides))

    if console.json_mode():
        return _finish_json({"ok": True, **summary})

    console.ok(f"{summary['distro']} ready at {installed_path}")
    if not args.dry_run:
        console.muted("next: plx shell            # enter the guest")
        console.muted("      plx recipe ls        # sample environments")
        console.muted("      plx doctor           # verify everything")
    return EXIT_OK


def cmd_rootfs(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    if args.action == "status":
        state = rootfs.status(cfg)
        if console.json_mode():
            return _finish_json(state)
        console.kv_block(
            {
                "rootfs": state["rootfs"],
                "installed": "yes" if state["populated"] else "no",
                "distro": state["distro_name"] or cfg.core.distro,
                "size": util.human_bytes(state["size"]) if state["size"] else "?",
                "shell": f"{state['shell']} ({'present' if state['shell_present'] else 'missing'})",
                "engine": state["engine"],
                "free space": util.human_bytes(state["free_space"]) if state["free_space"] else "?",
            }
        )
        if state["plx"]:
            console.header("plx marker")
            console.kv_block(state["plx"])
        return EXIT_OK
    if args.action == "remove":
        result = rootfs.remove(cfg, confirm=args.yes, dry_run=args.dry_run)
        if console.json_mode():
            return _finish_json(result)
        if result.get("removed"):
            console.ok(f"removed {result['rootfs']}")
        elif result.get("dry_run"):
            console.muted("dry-run: nothing deleted")
        else:
            console.info(result.get("reason", "nothing to do"))
        return EXIT_OK
    console.err(f"unknown rootfs action {args.action!r}")
    return EXIT_USAGE


# --------------------------------------------------------------------------
# shell / exec / mounts
# --------------------------------------------------------------------------
def cmd_shell(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    if args.show:
        payload = shell.info(cfg)
        if console.json_mode():
            return _finish_json(payload)
        console.kv_block(
            {
                "engine": payload["engine"],
                "rootfs": payload["rootfs"],
                "rootfs ready": "yes" if payload["rootfs_ready"] else "no",
                "workdir": payload["workdir"],
                "shell": payload["shell"],
            }
        )
        console.header("engine availability")
        console.table(
            ["engine", "available", "root?", "install"],
            [
                [
                    name,
                    "yes" if info["available"] else "no",
                    "yes" if info["needs_root"] else "no",
                    info["install"],
                ]
                for name, info in payload["engines"].items()
            ],
        )
        return EXIT_OK
    return shell.enter(
        cfg,
        args.command,
        engine=args.engine,
        login=not args.no_login,
        root=args.root,
        dry_run=args.dry_run,
    )


def cmd_exec(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    command = " ".join(args.command)
    if not command:
        console.err("nothing to run — usage: plx exec <command> [args...]")
        return EXIT_USAGE
    return shell.enter(
        cfg, command, engine=args.engine, login=False, root=args.root, dry_run=args.dry_run
    )


def cmd_mount(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    info = mounts.explain(cfg, engine=args.engine)
    if console.json_mode():
        return _finish_json(info)
    console.kv_block(
        {
            "engine": f"{info['engine']} ({'available' if info['engine_available'] else 'not available'})",
            "rootfs": info["rootfs"],
            "workdir": info["workdir"],
        }
    )
    console.header("bind mounts")
    console.table(
        ["source", "guest path", "mode"],
        [[bind["src"], bind["dst"], "ro" if bind["ro"] else "rw"] for bind in info["binds"]],
    )
    if info["skipped_binds"]:
        console.header("skipped (source missing)")
        console.bullet_list(info["skipped_binds"])
    if args.command:
        try:
            argv = mounts.engine_argv(cfg, None, engine=info["engine"])
        except mounts.MountError as exc:
            console.err(str(exc))
            return EXIT_FAIL
        console.header("command")
        console.out(shlex.join(argv))
    return EXIT_OK


# --------------------------------------------------------------------------
# services
# --------------------------------------------------------------------------
def _service_up() -> int:
    if supervisor.ping():
        console.ok(f"plxd already running (pid {supervisor.alive_pid()})")
        return EXIT_OK
    paths.ensure_layout()
    log = open(paths.daemon_log(), "ab", buffering=0)
    env = {**os.environ, "PLX_HOME": str(paths.home())}
    argv = [sys.executable, "-m", "plx.plxd", "run"]
    try:
        proc = subprocess.Popen(  # noqa: S603 - our own module
            argv,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
    except OSError as exc:
        console.err(f"could not start plxd: {exc}")
        return EXIT_FAIL
    if not supervisor.wait_for_socket(timeout=10.0):
        console.err(f"plxd did not come up — see {paths.daemon_log()}")
        return EXIT_FAIL
    console.ok(f"plxd running (pid {proc.pid}) · logs: {paths.daemon_log()}")
    specs = supervisor.load_services()
    if specs:
        console.muted("services: " + ", ".join(sorted(specs)))
    return EXIT_OK


def _service_down() -> int:
    if not supervisor.ping():
        console.info("plxd is not running")
        return EXIT_OK
    client = supervisor.SupervisorClient()
    client.shutdown()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and supervisor.ping(timeout=0.5):
        time.sleep(0.1)
    if supervisor.ping():
        console.warn("plxd is still shutting down")
        return EXIT_OK
    console.ok("plxd stopped")
    return EXIT_OK


def cmd_service(args: argparse.Namespace) -> int:
    _load_config(args)  # surfaces config warnings once; services live in their own file
    action = args.action

    if action == "up":
        return _service_up()
    if action == "down":
        return _service_down()
    if action == "daemon":
        return plxd_mod.main(["run"])

    if action == "example":
        target = paths.services_file()
        if target.exists() and not args.force:
            console.info(f"{target} already exists — use --force to overwrite")
            return EXIT_OK
        paths.ensure_layout()
        util.atomic_write(target, supervisor.DEFAULT_SERVICES_TEXT)
        console.ok(f"wrote {target}")
        return EXIT_OK

    if action == "edit":
        target = paths.services_file()
        if not target.exists():
            util.atomic_write(target, supervisor.DEFAULT_SERVICES_TEXT)
        editor = os.environ.get("EDITOR") or util.which("nano") or util.which("vi") or "vi"
        subprocess.run([editor, str(target)], check=False)
        try:
            specs = supervisor.load_services()
        except supervisor.ServiceError as exc:
            console.err(str(exc))
            return EXIT_FAIL
        console.ok(f"{len(specs)} service(s) defined")
        if supervisor.ping():
            try:
                supervisor.SupervisorClient().reload()
                console.ok("plxd reloaded")
            except supervisor.SupervisorError as exc:
                console.warn(f"reload failed: {exc}")
        return EXIT_OK

    try:
        specs = supervisor.load_services()
    except supervisor.ServiceError as exc:
        console.err(str(exc))
        return EXIT_FAIL

    live: dict[str, Any] = {}
    running = supervisor.ping()
    if running:
        try:
            live = supervisor.SupervisorClient().status().get("services", {})
        except supervisor.SupervisorError:
            running = False

    if action == "ls":
        if console.json_mode():
            return _finish_json(
                {
                    "daemon_running": running,
                    "services": {
                        name: {
                            **spec.to_dict(),
                            "state": live.get(name, {}).get("state", "unknown"),
                        }
                        for name, spec in sorted(specs.items())
                    },
                }
            )
        if not specs:
            console.info(f"no services defined in {paths.services_file()}")
            console.muted("start from the sample: plx service example")
            return EXIT_OK
        rows = [
            [
                name,
                "yes" if spec.enabled else "no",
                live.get(name, {}).get("state", "-") if running else "-",
                spec.restart,
                " ".join(spec.argv())[:40],
            ]
            for name, spec in sorted(specs.items())
        ]
        console.table(["service", "enabled", "state", "restart", "command"], rows)
        if not running:
            console.muted("\nplxd is not running — plx service up")
        return EXIT_OK

    if action == "status":
        if not running:
            state_path = paths.state_file()
            if console.json_mode():
                return _finish_json(
                    {"daemon": {"running": False}, "state_file": str(state_path), "services": {}}
                )
            console.warn("plxd is not running — plx service up")
            if state_path.exists():
                console.muted(f"last known state: {state_path}")
            return EXIT_OK
        data = supervisor.SupervisorClient().status()
        if console.json_mode():
            return _finish_json(data)
        daemon = data["daemon"]
        console.kv_block(
            {
                "pid": daemon["pid"],
                "uptime": util.human_duration(daemon["uptime"]),
                "socket": daemon["socket"],
                "services file": daemon["services_file"],
            }
        )
        headers, rows = supervisor.format_status_table(data)
        console.header("services")
        console.table(headers, rows)
        return EXIT_OK

    if action in {"start", "stop", "restart"}:
        if not running:
            console.err("plxd is not running — plx service up")
            return EXIT_FAIL
        client = supervisor.SupervisorClient()
        name = args.name
        if not name and action == "start" and len(specs) == 1:
            name = next(iter(specs))
        if not name:
            console.err(f"which service? usage: plx service {action} <name>")
            return EXIT_USAGE
        result = getattr(client, action)(name)
        if console.json_mode():
            return _finish_json(result)
        console.ok(f"{name}: {result.get('state')} (pid {result.get('pid') or '-'})")
        return EXIT_OK

    if action == "logs":
        name = args.name
        if not name:
            console.err("usage: plx service logs <name> [-n LINES]")
            return EXIT_USAGE
        if name not in specs:
            console.err(f"unknown service {name!r}")
            return EXIT_FAIL
        lines = util.tail_lines(paths.service_log(name), args.lines)
        if console.json_mode():
            return _finish_json({"service": name, "lines": lines})
        if not lines:
            console.info(f"{paths.service_log(name)} is empty")
        for line in lines:
            console.out(line)
        return EXIT_OK

    if action == "reload":
        if not running:
            console.err("plxd is not running — plx service up")
            return EXIT_FAIL
        result = supervisor.SupervisorClient().reload()
        if console.json_mode():
            return _finish_json(result)
        console.ok(f"reloaded ({len(result['services'])} services)")
        return EXIT_OK

    console.err(f"unknown service action {action!r}")
    return EXIT_USAGE


# --------------------------------------------------------------------------
# recipes
# --------------------------------------------------------------------------
def cmd_recipe(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    action = args.action

    if action == "ls":
        catalog = recipes.discover()
        entries = []
        for name, path in sorted(catalog.items()):
            try:
                recipe = recipes.load(path)
            except recipes.RecipeError:
                continue
            entries.append(
                {
                    "name": name,
                    "description": recipe.description,
                    "base": recipe.base,
                    "packages": {k: len(v) for k, v in recipe.packages.items()},
                    "services": sorted(recipe.services),
                    "path": str(path),
                }
            )
        if console.json_mode():
            return _finish_json(
                {"recipes": entries, "directories": [str(d) for d in recipes.recipe_dirs()]}
            )
        if not entries:
            console.info("no recipes found")
            return EXIT_OK
        console.table(
            ["recipe", "base", "packages", "services", "description"],
            [
                [
                    entry["name"],
                    entry["base"] or "-",
                    ", ".join(f"{k}×{v}" for k, v in entry["packages"].items() if v) or "-",
                    ", ".join(entry["services"]) or "-",
                    entry["description"][:40],
                ]
                for entry in entries
            ],
        )
        console.muted("\napply: plx recipe apply <name>")
        return EXIT_OK

    if action == "show":
        path = recipes.resolve(args.name)
        recipe = recipes.load(path)
        if console.json_mode():
            return _finish_json(recipe.to_dict())
        recipes.render(recipe)
        return EXIT_OK

    if action == "apply":
        path = recipes.resolve(args.name or "")
        recipe = recipes.load(path)
        report = recipes.apply(
            recipe,
            cfg,
            dry_run=args.dry_run,
            engine=args.engine,
            with_services=not args.no_services,
            install_base=args.install_base,
        )
        if console.json_mode():
            _emit_json(report)
        else:
            console.out(console.paint(f"applying {recipe.name}", "bold"))
            recipes.render_report(report)
        return EXIT_OK if report["ok"] or args.dry_run else EXIT_FAIL

    if action == "copy":
        source = recipes.resolve(args.name or "")
        target = recipes.copy_into_user_dir(source, force=args.force)
        console.ok(f"{target}")
        return EXIT_OK

    console.err(f"unknown recipe action {action!r}")
    return EXIT_USAGE


# --------------------------------------------------------------------------
# hardware bridge
# --------------------------------------------------------------------------
def cmd_hw(args: argparse.Namespace) -> int:
    action = (args.action or "status").lower()
    extra = list(args.extra or [])

    if action == "ls":
        tool_rows = [
            [
                tool.name,
                "yes" if tool.present else "no",
                tool.binary,
                tool.description[:44],
            ]
            for tool in hw.tools()
        ]
        if console.json_mode():
            return _finish_json({"tools": [tool.to_dict() for tool in hw.tools()]})
        console.table(["tool", "available", "binary", "description"], tool_rows)
        console.muted("\ninstall: pkg install termux-api  +  the Termux:API app")
        return EXIT_OK

    if action == "status":
        data = hw.status()
        if console.json_mode():
            return _finish_json(data)
        if not data["termux_api"]:
            console.warn("Termux:API is not installed")
            console.muted(data.get("hint", ""))
            return EXIT_OK
        console.header("hardware snapshot")
        for name, value in data["data"].items():
            console.out(f"  {console.paint(name, 'cyan')}: {value}")
        return EXIT_OK

    if action == "call":
        if not extra:
            console.err("usage: plx hw call <tool> [args...]   (see: plx hw ls)")
            return EXIT_USAGE
        action, extra = extra[0], extra[1:]

    if action == "clip":
        action = "clipboard-set" if extra else "clipboard-get"
        extra = extra[:1] if extra else []

    if action not in hw.TOOLS:
        console.err(f"unknown hardware tool {action!r} — try: plx hw ls")
        return EXIT_USAGE

    result = hw.call(action, extra)
    if console.json_mode():
        _emit_json(result)
        return EXIT_OK if result["ok"] else EXIT_FAIL
    if not result["ok"]:
        console.err(result["stderr"] or f"{action} failed (exit {result['code']})")
        return EXIT_FAIL
    if result.get("json") is not None:
        _emit_json(result["json"])
    else:
        console.out(result["stdout"])
    return EXIT_OK


# --------------------------------------------------------------------------
# backups
# --------------------------------------------------------------------------
def cmd_backup(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    action = args.action

    if action == "create":
        manifest = backup.create(
            cfg,
            dest=args.dest,
            label=args.label,
            compress=args.compress,
            dry_run=args.dry_run,
        )
        if console.json_mode():
            return _finish_json(manifest)
        if args.dry_run:
            return EXIT_OK
        console.muted("restore with: plx backup restore " + str(manifest["archive"]))
        if args.prune:
            backup.prune(keep=args.prune)
        return EXIT_OK

    if action == "ls":
        entries = backup.list_backups(args.dest)
        if console.json_mode():
            return _finish_json({"backups": entries})
        if not entries:
            console.info("no backups yet — plx backup create")
            return EXIT_OK
        console.table(
            ["archive", "size", "created", "distro", "verified"],
            [
                [
                    entry["name"],
                    util.human_bytes(entry["size"]),
                    entry["modified"],
                    entry["distro"],
                    "yes" if entry["verified"] else "no",
                ]
                for entry in entries
            ],
        )
        return EXIT_OK

    if action == "verify":
        result = backup.verify(args.archive)
        if console.json_mode():
            _emit_json(result)
        elif result.get("verified"):
            console.ok(f"verified {result['archive']}")
        else:
            console.warn(f"not verified: {result.get('reason', 'hash mismatch')}")
        return EXIT_OK if result.get("verified") else EXIT_FAIL

    if action == "restore":
        result = backup.restore(
            args.archive,
            cfg,
            confirm=args.yes,
            dry_run=args.dry_run,
            skip_verify=args.skip_verify,
        )
        if console.json_mode():
            return _finish_json(result)
        if result.get("restored"):
            console.ok(f"restored into {result['rootfs']}")
            if result.get("aside"):
                console.muted(f"previous rootfs kept at {result['aside']}")
        elif result.get("dry_run"):
            console.muted("dry-run: nothing extracted")
        return EXIT_OK

    if action == "prune":
        result = backup.prune(keep=args.keep, directory=args.dest, dry_run=args.dry_run)
        if console.json_mode():
            return _finish_json(result)
        console.ok(f"removed {len(result['removed'])} snapshot(s), kept {len(result['kept'])}")
        return EXIT_OK

    console.err(f"unknown backup action {action!r}")
    return EXIT_USAGE


# --------------------------------------------------------------------------
# networking
# --------------------------------------------------------------------------
def cmd_net(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    action = args.action

    if action == "ip":
        payload = {"hostname": net.hostname(), "addresses": net.local_ips()}
        if console.json_mode():
            return _finish_json(payload)
        console.kv_block(payload)
        return EXIT_OK

    if action == "ports":
        entries = net.listening_ports()
        if console.json_mode():
            return _finish_json({"ports": entries})
        if not entries:
            console.info("no listening TCP sockets")
            return EXIT_OK
        console.table(
            ["port", "proto", "address", "exposed"],
            [
                [
                    str(entry["port"]),
                    entry["proto"],
                    entry["addr"],
                    "yes" if entry["exposed"] else "no",
                ]
                for entry in entries
            ],
        )
        return EXIT_OK

    if action == "ssh":
        if not _need_rootfs(cfg):
            return EXIT_FAIL
        key = net.ensure_ssh_key(cfg, force=args.force)
        info = net.session_info(cfg)
        payload = {**info, "key": key}
        if console.json_mode():
            return _finish_json(payload)
        net.banner(cfg)
        if key.get("created"):
            console.ok(f"created {key['path']}")
        console.muted(f"\npublic key:\n  {key.get('public', '(missing)')}")
        console.muted(f"\n{payload['hint']}")
        return EXIT_OK

    if action == "sshd-config":
        if not _need_rootfs(cfg):
            return EXIT_FAIL
        result = net.write_sshd_config(cfg, password_auth=args.password_auth, force=args.force)
        if console.json_mode():
            return _finish_json(result)
        console.ok(f"{'wrote' if result['changed'] else 'unchanged'}: {result['path']}")
        console.muted("start it: plx service start sshd   (needs openssh-server in the guest)")
        return EXIT_OK

    if action == "doctor":
        payload = net.diagnose(cfg)
        if console.json_mode():
            return _finish_json(payload)
        console.kv_block(
            {
                "hostname": payload["hostname"],
                "addresses": ", ".join(payload["ips"]) or "-",
                "ssh port": f"{cfg.net.ssh_port} ({'free' if payload['ssh_port_free'] else 'in use'})",
                "sshd in guest": "yes" if payload["sshd_present"] else "no",
            }
        )
        return EXIT_OK

    console.err(f"unknown net action {action!r}")
    return EXIT_USAGE


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------
def cmd_gui(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    action = args.action

    if action == "status":
        payload = gui.status(cfg)
        if console.json_mode():
            return _finish_json(payload)
        console.kv_block(
            {
                "server": payload["server_binary"] or "not installed",
                "display": payload["display"],
                "running": "yes" if payload["running"] else "no",
                "desktop": payload["desktop"],
                "session": payload["session_command"],
            }
        )
        if payload["install_hint"]:
            console.muted(payload["install_hint"])
        return EXIT_OK

    if action == "start":
        try:
            payload = gui.start(cfg, dry_run=args.dry_run)
        except RuntimeError as exc:
            console.err(str(exc))
            return EXIT_FAIL
        if console.json_mode():
            return _finish_json(payload)
        if payload.get("started"):
            console.ok(f"Termux:X11 on {payload['display']} (pid {payload['pid']})")
            console.muted(f"launch the desktop: {payload.get('next')}")
        return EXIT_OK

    if action == "stop":
        payload = gui.stop(cfg, dry_run=args.dry_run)
        if console.json_mode():
            return _finish_json(payload)
        if payload.get("stopped"):
            console.ok("stopped")
        else:
            console.info(payload.get("reason", "nothing to stop"))
        return EXIT_OK

    if action == "session":
        if not _need_rootfs(cfg):
            return EXIT_FAIL
        return gui.session(cfg, args.desktop, engine=args.engine)

    console.err(f"unknown gui action {action!r}")
    return EXIT_USAGE


# --------------------------------------------------------------------------
# security
# --------------------------------------------------------------------------
def cmd_security(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    action = args.action
    if action == "report":
        payload = security.report(cfg)
        if console.json_mode():
            return _finish_json(payload)
        security.render(payload)
        return EXIT_OK
    if action == "harden":
        result = security.harden(cfg, apply=args.apply, dry_run=args.dry_run)
        if console.json_mode():
            return _finish_json(result)
        for entry in result["actions"]:
            prefix = console.paint("✓", "green") if entry["applied"] else console.paint("·", "grey")
            console.out(f"{prefix} {entry['action']}: {entry['target']}")
            if entry.get("detail"):
                console.muted(f"    {entry['detail']}")
        if not result["applied"]:
            console.muted("\nnothing changed — re-run with --apply")
        return EXIT_OK
    console.err(f"unknown security action {action!r}")
    return EXIT_USAGE


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------
def _add_common(parser: argparse.ArgumentParser, *, suppress: bool) -> None:
    default_true = argparse.SUPPRESS if suppress else False
    parser.add_argument("--json", action="store_true", default=default_true, help="JSON output")
    parser.add_argument(
        "-q", "--quiet", action="store_true", default=default_true, help="suppress human output"
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=argparse.SUPPRESS,
        help="disable ANSI colours",
    )
    parser.add_argument(
        "--home", default=argparse.SUPPRESS, help="override PLX_HOME (default ~/.plx)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plx",
        description="PocketLinux — a real Linux workstation inside your own phone.",
        epilog="Run `plx <command> --help` for details. Docs: docs/ in the repository.",
    )
    parser.add_argument("--version", action="version", version=f"plx {__version__}")
    _add_common(parser, suppress=False)
    common = argparse.ArgumentParser(add_help=False)
    _add_common(common, suppress=True)
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    def add(name: str, help_text: str, handler: Handler, **kwargs: Any) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_text, description=help_text, parents=[common], **kwargs)
        sp.set_defaults(handler=handler)
        return sp

    add("version", "print version information", cmd_version)
    add("info", "device, rootfs and engine overview", cmd_info)
    add("doctor", "diagnose the installation with fix suggestions", cmd_doctor)

    config_parser = add("config", "inspect or change ~/.plx/config.toml", cmd_config)
    config_sub = config_parser.add_subparsers(dest="action", metavar="<action>")
    config_sub.add_parser("show", help="print the effective config", parents=[common])
    config_sub.add_parser("path", help="print the config file path", parents=[common])
    init_parser = config_sub.add_parser("init", help="write a default config", parents=[common])
    init_parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    set_parser = config_sub.add_parser("set", help="set one value", parents=[common])
    set_parser.add_argument("key", help="section.key, e.g. core.engine")
    set_parser.add_argument("value", help="new value")
    config_sub.add_parser("edit", help="open the config in $EDITOR", parents=[common])

    install_parser = add("install", "install a root filesystem", cmd_install)
    install_parser.add_argument("distro", nargs="?", help="distribution name (default: config)")
    install_parser.add_argument("--list", action="store_true", help="list available images")
    install_parser.add_argument("--arch", help="override the detected architecture")
    install_parser.add_argument("--dest", help="install into a custom directory")
    install_parser.add_argument("--url", help="install from a custom tarball URL")
    install_parser.add_argument("--force", action="store_true", help="replace an existing rootfs")
    install_parser.add_argument("--dry-run", action="store_true", help="print, do not execute")

    rootfs_parser = add("rootfs", "inspect or remove the installed rootfs", cmd_rootfs)
    rootfs_sub = rootfs_parser.add_subparsers(dest="action", metavar="<action>")
    rootfs_sub.add_parser("status", help="show rootfs details", parents=[common])
    remove_parser = rootfs_sub.add_parser("remove", help="delete the rootfs", parents=[common])
    remove_parser.add_argument("--yes", action="store_true", help="required confirmation")
    remove_parser.add_argument("--dry-run", action="store_true", help="print, do not delete")

    shell_parser = add("shell", "enter the guest shell", cmd_shell)
    shell_parser.add_argument("-c", "--command", help="run one command instead of a shell")
    shell_parser.add_argument("--engine", choices=("proot", "chroot"), help="override the engine")
    shell_parser.add_argument("--root", action="store_true", help="use the chroot engine (su)")
    shell_parser.add_argument(
        "--no-login", action="store_true", help="interactive, not login shell"
    )
    shell_parser.add_argument("--dry-run", action="store_true", help="print the command only")
    shell_parser.add_argument("--show", action="store_true", help="explain the session")

    exec_parser = add("exec", "run a command inside the guest", cmd_exec)
    exec_parser.add_argument("command", nargs=argparse.REMAINDER, help="command and arguments")
    exec_parser.add_argument("--engine", choices=("proot", "chroot"), help="override the engine")
    exec_parser.add_argument("--root", action="store_true", help="use the chroot engine (su)")
    exec_parser.add_argument("--dry-run", action="store_true", help="print the command only")

    mount_parser = add("mount", "show the bind-mount plan", cmd_mount)
    mount_parser.add_argument(
        "action", nargs="?", default="show", choices=("show",), help="show (default)"
    )
    mount_parser.add_argument("--engine", choices=("proot", "chroot"), help="engine to explain")
    mount_parser.add_argument(
        "--command", action="store_true", help="also print the full engine argv"
    )

    service_parser = add("service", "manage guest services with plxd", cmd_service)
    service_sub = service_parser.add_subparsers(dest="action", metavar="<action>")
    service_sub.add_parser("ls", help="list defined services", parents=[common])
    service_sub.add_parser("status", help="daemon and service status", parents=[common])
    service_sub.add_parser("up", help="start plxd in the background", parents=[common])
    service_sub.add_parser("down", help="stop plxd", parents=[common])
    service_sub.add_parser("daemon", help="run plxd in the foreground", parents=[common])
    service_sub.add_parser("reload", help="reload services.toml", parents=[common])
    example_parser = service_sub.add_parser(
        "example", help="write a sample services.toml", parents=[common]
    )
    example_parser.add_argument("--force", action="store_true")
    service_sub.add_parser("edit", help="edit services.toml and reload", parents=[common])
    for name, help_text in (
        ("start", "start a service"),
        ("stop", "stop a service"),
        ("restart", "restart a service"),
    ):
        sp = service_sub.add_parser(name, help=help_text, parents=[common])
        sp.add_argument("name", nargs="?", help="service name")
    logs_parser = service_sub.add_parser("logs", help="show a service log", parents=[common])
    logs_parser.add_argument("name", help="service name")
    logs_parser.add_argument("-n", "--lines", type=int, default=100, help="number of lines")

    recipe_parser = add("recipe", "declarative guest environments", cmd_recipe)
    recipe_sub = recipe_parser.add_subparsers(dest="action", metavar="<action>")
    recipe_sub.add_parser("ls", help="list available recipes", parents=[common])
    show_parser = recipe_sub.add_parser("show", help="describe a recipe", parents=[common])
    show_parser.add_argument("name")
    apply_parser = recipe_sub.add_parser(
        "apply", help="apply a recipe to the guest", parents=[common]
    )
    apply_parser.add_argument("name")
    apply_parser.add_argument("--dry-run", action="store_true", help="print, do not install")
    apply_parser.add_argument("--engine", choices=("proot", "chroot"))
    apply_parser.add_argument("--no-services", action="store_true", help="skip service definitions")
    apply_parser.add_argument("--install-base", action="store_true", help="install the base rootfs")
    copy_parser = recipe_sub.add_parser(
        "copy", help="copy a recipe to ~/.plx/recipes", parents=[common]
    )
    copy_parser.add_argument("name")
    copy_parser.add_argument("--force", action="store_true")

    hw_parser = add(
        "hw",
        "phone hardware via Termux:API (use `--` before tool-specific flags)",
        cmd_hw,
    )
    hw_parser.add_argument("action", nargs="?", help="ls | status | call | <tool>")
    hw_parser.add_argument(
        "extra",
        nargs="*",
        help="arguments passed to the tool (put tool flags after a `--`)",
    )

    backup_parser = add("backup", "snapshot and restore the guest rootfs", cmd_backup)
    backup_sub = backup_parser.add_subparsers(dest="action", metavar="<action>")
    create_parser = backup_sub.add_parser("create", help="create a snapshot", parents=[common])
    create_parser.add_argument("--dest", help="directory for the archive")
    create_parser.add_argument("--label", help="suffix for the archive name")
    create_parser.add_argument(
        "--compress", choices=("auto", "zstd", "gzip", "none"), default="auto"
    )
    create_parser.add_argument("--prune", type=int, default=0, help="keep only N newest afterwards")
    create_parser.add_argument("--dry-run", action="store_true")
    ls_parser = backup_sub.add_parser("ls", help="list snapshots", parents=[common])
    ls_parser.add_argument("--dest", help="directory to scan")
    verify_parser = backup_sub.add_parser("verify", help="check an archive hash", parents=[common])
    verify_parser.add_argument("archive")
    restore_parser = backup_sub.add_parser("restore", help="replace the rootfs", parents=[common])
    restore_parser.add_argument("archive")
    restore_parser.add_argument("--yes", action="store_true", help="required confirmation")
    restore_parser.add_argument("--skip-verify", action="store_true", help="skip the hash check")
    restore_parser.add_argument("--dry-run", action="store_true")
    prune_parser = backup_sub.add_parser("prune", help="delete old snapshots", parents=[common])
    prune_parser.add_argument("--keep", type=int, default=5)
    prune_parser.add_argument("--dest")
    prune_parser.add_argument("--dry-run", action="store_true")

    net_parser = add("net", "addresses, ports, SSH keys and sshd config", cmd_net)
    net_sub = net_parser.add_subparsers(dest="action", metavar="<action>")
    net_sub.add_parser("ip", help="show addresses", parents=[common])
    net_sub.add_parser("ports", help="show listening TCP sockets", parents=[common])
    net_sub.add_parser("doctor", help="network diagnostics", parents=[common])
    ssh_parser = net_sub.add_parser(
        "ssh", help="create a key and print the ssh command", parents=[common]
    )
    ssh_parser.add_argument("--force", action="store_true", help="regenerate the key")
    sshd_parser = net_sub.add_parser(
        "sshd-config", help="write a safe sshd_config", parents=[common]
    )
    sshd_parser.add_argument("--password-auth", action="store_true", help="allow passwords")
    sshd_parser.add_argument("--force", action="store_true", help="overwrite an existing file")

    gui_parser = add("gui", "optional desktop via Termux:X11", cmd_gui)
    gui_sub = gui_parser.add_subparsers(dest="action", metavar="<action>")
    gui_sub.add_parser("status", help="desktop status", parents=[common])
    gui_start = gui_sub.add_parser("start", help="start the X server", parents=[common])
    gui_start.add_argument("--dry-run", action="store_true")
    gui_stop = gui_sub.add_parser("stop", help="stop the X server", parents=[common])
    gui_stop.add_argument("--dry-run", action="store_true")
    gui_session = gui_sub.add_parser("session", help="run the desktop session", parents=[common])
    gui_session.add_argument("--desktop", help="xfce | lxqt | mate | fluxbox | openbox | xterm")
    gui_session.add_argument("--engine", choices=("proot", "chroot"))

    security_parser = add("security", "honest security posture and hardening", cmd_security)
    security_sub = security_parser.add_subparsers(dest="action", metavar="<action>")
    security_sub.add_parser(
        "report", help="what is actually true about this device", parents=[common]
    )
    harden_parser = security_sub.add_parser("harden", help="apply safe defaults", parents=[common])
    harden_parser.add_argument("--apply", action="store_true", help="actually write changes")
    harden_parser.add_argument("--dry-run", action="store_true", help="list the plan only")

    parser.set_defaults(handler=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    home = getattr(args, "home", None)
    if home:
        os.environ["PLX_HOME"] = str(Path(home).expanduser())

    color: bool | None = None
    if getattr(args, "no_color", False):
        color = False

    console.configure(
        json_mode=bool(getattr(args, "json", False)),
        quiet=bool(getattr(args, "quiet", False)),
        color=color,
    )

    handler: Handler | None = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return EXIT_OK

    try:
        return handler(args)
    except KeyboardInterrupt:
        console.err("interrupted")
        return 130
    except (
        config_mod.ConfigError,
        rootfs.RootfsError,
        shell.ShellError,
        supervisor.SupervisorError,
        supervisor.ServiceError,
        recipes.RecipeError,
        backup.BackupError,
        mounts.MountError,
        FileNotFoundError,
        RuntimeError,
        KeyError,
        ValueError,
    ) as exc:
        message = str(exc) or exc.__class__.__name__
        if console.json_mode():
            console.json_out({"ok": False, "error": message})
        else:
            console.err(message)
        return EXIT_USAGE
    except Exception as exc:  # pragma: no cover - safety net
        if os.environ.get("PLX_DEBUG"):
            raise
        message = f"{type(exc).__name__}: {exc}"
        if console.json_mode():
            console.json_out({"ok": False, "error": message})
        else:
            console.err(message)
            console.muted("set PLX_DEBUG=1 for a full traceback")
        return EXIT_FAIL


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
