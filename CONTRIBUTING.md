# Contributing to PocketLinux

Thanks for helping. This project has an unusual constraint set, so please read the four rules
before opening a PR.

## 1. Runtime dependencies stay at zero

`plx` runs inside Termux on phones. Every import must be Python standard library (3.11+). If you
need JSON, use `json`; TOML, use `tomllib`; HTTP, use `urllib`. Dev-only tools (`pytest`, `ruff`)
belong in `[project.optional-dependencies].dev`.

## 2. Every behaviour gets a test

```bash
make test        # pytest
make lint        # ruff check + format check
make check       # both
```

Tests must run against a temporary `PLX_HOME` (the `plx_home` fixture) and must not require a
phone, network access, root, or `proot`. If your code path genuinely needs a binary, guard the test
with `pytest.mark.skipif(util.which("…") is None, …)`.

The bar we hold ourselves to:

* new module → tests for its happy path **and** its failure path;
* new CLI command → at least one human-output test and one `--json` test;
* new check in `doctor.py` → a test asserting the status and that `fix` names a command.

## 3. Never mutate a device silently

Anything that writes to the host or the guest must:

* support `--dry-run` (print the exact command, change nothing);
* refuse dangerous operations without explicit confirmation (`--yes`);
* keep everything under `PLX_HOME` unless it is a documented bind mount;
* report what it did in the return value / JSON output.

## 4. Errors must name the fix

Bad: `FileNotFoundError: proot`.
Good:

```
✗ proot is not installed — run: pkg install proot
  (or use the chroot engine on a rooted device: plx shell --engine chroot)
```

## Scope boundary — read this first

PocketLinux is **not** a rooting tool, and PRs that add exploit chains, privilege escalation,
lock-screen bypasses, stealth/persistence outside `PLX_HOME`, or anything that targets devices the
operator does not own will be closed without discussion. "Ground-level access" here means real
Linux mechanisms on hardware you control.

## Workflow

```bash
git clone https://github.com/haanwoh/knullSU && cd knullSU
python3 -m pip install -e '.[dev]'
make check
git checkout -b feature/your-thing
# … code, tests, docs …
make check
```

PR checklist:

- [ ] `make check` is green
- [ ] new flags are documented in `docs/12-cli-reference.md` and in the command's `--help`
- [ ] new behaviour is covered by a test
- [ ] no new runtime dependency
- [ ] no writes outside `PLX_HOME` without `--yes`
- [ ] commit messages say *why*, not just *what*

## Style

* `ruff format`, line length 100, double quotes;
* type hints on public functions (`from __future__ import annotations`);
* dataclasses for structured data, dicts only at JSON boundaries;
* docstrings explain the *reasoning*, not the mechanics;
* keep CLI handlers under ~30 lines; move logic into a module so it can be tested.

## Reporting bugs

```bash
plx version --json
plx doctor --json
PLX_DEBUG=1 plx <failing command>
tail -50 ~/.plx/logs/plxd.log
```

Redact IPs/SSIDs/hostnames. Security issues: [SECURITY.md](SECURITY.md), not the issue tracker.
