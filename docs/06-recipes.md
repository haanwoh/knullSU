# 06 · Recipes

A recipe is one TOML file that describes an environment: packages, services, hooks, suggested
mounts. Apply it on a new phone and you get the same box back — months later, without remembering
which `apt install` you ran.

```bash
plx recipe ls
plx recipe show devbox
plx recipe apply devbox --dry-run     # always look first
plx recipe apply devbox
```

## Bundled recipes

| name | base | contents |
|---|---|---|
| `devbox` | ubuntu | git, build-essential, python3, node/npm, ripgrep, tmux, neovim, httpie, typescript, a static file server service |
| `datascience` | ubuntu | numpy, pandas, scipy, scikit-learn, matplotlib, JupyterLab (loopback, port 8888) |
| `webdev` | ubuntu | node, pnpm, typescript, vite, a dev-server service |
| `minimal` | alpine | git, curl, bash, nano, openssh + a supervised `sshd` |

Copy one and edit it:

```bash
plx recipe copy devbox       # → ~/.plx/recipes/devbox.toml
plx recipe show ~/.plx/recipes/devbox.toml
```

## Format

```toml
[recipe]
name = "devbox"                       # defaults to the file name
description = "git, compilers, node"
base = "ubuntu"                       # only used with --install-base
notes = """
Free-form text shown by `plx recipe show`.
"""

[env]                                 # suggestions, not exported automatically
EDITOR = "nvim"

[mounts]                              # suggestions, printed after apply
extra = ["/sdcard/Download:/root/downloads"]

[packages]
apt = ["git", "curl", "build-essential"]
pip = ["httpie"]                      # python3 -m pip install
npm = ["typescript"]                  # npm install -g

[hooks]
pre_install = ["echo starting"]
post_install = ["git config --global init.defaultBranch main"]

[services.web]                        # merged into ~/.plx/services.toml
command = "python3 -m http.server 8000 --bind 127.0.0.1"
restart = "on-failure"
restart_delay = 3.0
dir = "/root/projects"
description = "static server"
```

Notes:

* the package manager is **detected** inside the guest (`apt-get` or `apk`); a recipe with an
  `apt` list applied to Alpine simply skips those packages and says so;
* `apk` lists are installed with `apk add --no-cache`;
* `pip` first tries `--break-system-packages` (Ubuntu 24.04 is PEP 668-managed) and retries
  without the flag if the pip version rejects it;
* every step is recorded: exit status, short detail, last 4 KB of output — so `--json` gives you a
  machine-readable build log;
* a failed step does not abort the run by default (you see the whole picture), but the command's
  exit code is non-zero.

## Apply order

1. rootfs present? (else `--install-base` installs `[recipe].base`)
2. package manager detection
3. `pre_install` hooks
4. system packages (`apt-get update` → `install`)
5. `pip` packages
6. `npm` packages
7. `post_install` hooks
8. services merged into `services.toml`, `plxd` reloaded if running
9. suggestions printed (env vars, mounts)

## Writing your own

```bash
plx recipe copy minimal
$EDITOR ~/.plx/recipes/minimal.toml
plx recipe apply minimal --dry-run
```

Keep recipes **idempotent** — `apt-get install` and `pip install` are; your hooks should be too
(`mkdir -p`, `test -f ||`, `git config`).

Real-world example, a C/C++ box:

```toml
[recipe]
name = "cdev"
base = "ubuntu"

[packages]
apt = ["build-essential", "cmake", "ninja-build", "gdb", "clang", "pkg-config", "git"]
pip = ["cmake"]
```

## Limitations

* `pip`/`npm` global installs inside a proot guest can be slow; prefer a virtualenv/`pnpm` for
  daily work and keep recipes to the essentials.
* Recipes do not have conditionals or loops — that is deliberate. If you need logic, put it in a
  hook, where it is visible.
* Services in a recipe are merged by name: re-applying overwrites existing definitions with the
  same name.
