#!/usr/bin/env bash
# PocketLinux bootstrap for Termux (and for testing on plain Linux).
#
#   curl -fsSL https://raw.githubusercontent.com/haanwoh/knullSU/main/install.sh | bash
#
# What it does, in order:
#   1. verifies this is Termux (or forces it with --force)
#   2. installs the handful of packages plx needs
#   3. links bin/plx into ~/.local/bin and fixes PATH
#   4. writes ~/.plx/config.toml and runs `plx doctor`
#
# It never touches /system, never requests root, and never edits anything
# outside the repo, ~/.local/bin, ~/.bashrc and ~/.plx.
set -euo pipefail

REPO_URL="${PLX_REPO_URL:-https://github.com/haanwoh/knullSU.git}"
INSTALL_DIR="${PLX_INSTALL_DIR:-$HOME/.local/share/pocketlinux}"
BIN_DIR="${PLX_BIN_DIR:-$HOME/.local/bin}"
ASSUME_YES=0
SKIP_PACKAGES=0
FORCE=0
PACKAGES="python proot termux-api openssh rsync tar zstd curl git"

log()  { printf '\033[36m▸\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
PocketLinux installer

  --yes            accept package installation without prompting
  --no-packages    skip `pkg install` (already have the deps)
  --dir DIR        install the checkout into DIR (default ~/.local/share/pocketlinux)
  --force          continue even if Termux is not detected
  --help           this text

Environment: PLX_REPO_URL, PLX_INSTALL_DIR, PLX_BIN_DIR
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) ASSUME_YES=1 ;;
    --no-packages) SKIP_PACKAGES=1 ;;
    --dir) INSTALL_DIR="${2:?--dir needs a value}"; shift ;;
    --force) FORCE=1 ;;
    --help|-h) usage; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
  shift
done

is_termux() {
  [ -n "${TERMUX_VERSION:-}" ] || \
  [ -d /data/data/com.termux ] || \
  case "${PREFIX:-}" in *com.termux*) true ;; *) false ;; esac
}

if ! is_termux && [ "$FORCE" -eq 0 ]; then
  die "this does not look like Termux. Re-run with --force to continue anyway."
fi

if is_termux; then
  command -v pkg >/dev/null 2>&1 || die "pkg not found — is this really Termux?"
  if [ "$SKIP_PACKAGES" -eq 0 ]; then
    if [ "$ASSUME_YES" -eq 0 ]; then
      printf 'Install packages: %s ? [Y/n] ' "$PACKAGES"
      read -r reply
      case "$reply" in [nN]*) SKIP_PACKAGES=1 ;; esac
    fi
  fi
  if [ "$SKIP_PACKAGES" -eq 0 ]; then
    log "pkg update"
    pkg update -y >/dev/null 2>&1 || warn "pkg update failed — continuing"
    log "pkg install $PACKAGES"
    # shellcheck disable=SC2086
    pkg install -y $PACKAGES || die "package installation failed"
    ok "dependencies installed"
  fi
fi

# ---- locate or fetch the source -------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/bin/plx" ]; then
  SRC="$SCRIPT_DIR"
  log "using the existing checkout at $SRC"
else
  if [ -d "$INSTALL_DIR/.git" ]; then
    log "updating $INSTALL_DIR"
    git -C "$INSTALL_DIR" pull --ff-only || warn "git pull failed — using what is on disk"
  else
    command -v git >/dev/null 2>&1 || die "git is required to fetch PocketLinux"
    log "cloning into $INSTALL_DIR"
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
  fi
  SRC="$INSTALL_DIR"
fi
[ -f "$SRC/bin/plx" ] || die "no bin/plx in $SRC — is this the PocketLinux repo?"

# ---- wire up the launcher --------------------------------------------------
mkdir -p "$BIN_DIR"
chmod +x "$SRC/bin/plx"
ln -sf "$SRC/bin/plx" "$BIN_DIR/plx"
ok "linked $BIN_DIR/plx"

SHELL_RC="$HOME/.bashrc"
if ! grep -qs 'PocketLinux' "$SHELL_RC"; then
  {
    printf '\n# PocketLinux\n'
    # $PATH must stay literal here: it belongs to the shell that reads .bashrc.
    # shellcheck disable=SC2016
    printf 'case ":$PATH:" in *":%s:"*) ;; *) export PATH="%s:$PATH" ;; esac\n' "$BIN_DIR" "$BIN_DIR"
  } >> "$SHELL_RC"
  ok "added $BIN_DIR to PATH in $SHELL_RC"
fi
export PATH="$BIN_DIR:$PATH"

# ---- first run -------------------------------------------------------------
log "writing ~/.plx/config.toml"
"$SRC/bin/plx" config init >/dev/null || warn "config init failed"

ok "installed — next steps"
cat <<'NEXT'

  plx doctor                # verify the environment
  plx install alpine        # ~150 MiB, fastest first rootfs
  plx install ubuntu        # ~1.5 GiB, full apt ecosystem
  plx shell                 # drop into Linux
  plx recipe ls             # devbox / datascience / webdev / minimal
  plx security report       # honest device posture

Optional Termux:API app (battery, sensors, torch, clipboard):
  https://f-droid.org/packages/com.termux.api/

NEXT
"$SRC/bin/plx" doctor || true
