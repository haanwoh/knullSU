# bash completion for plx
#   source scripts/completion.bash
# or install it:
#   cp scripts/completion.bash ~/.local/share/bash-completion/completions/plx

_plx_commands="version info doctor config install rootfs shell exec mount service recipe hw backup net gui security"

# Fill COMPREPLY from a space-separated candidate list without word-splitting surprises.
_plx_complete() {
  local -a candidates=()
  mapfile -t candidates < <(compgen -W "$1" -- "$2")
  COMPREPLY=("${candidates[@]}")
}

_plx_services() {
  local file="${PLX_HOME:-$HOME/.plx}/services.toml"
  [ -f "$file" ] || return 0
  sed -n 's/^\[service\.\([A-Za-z0-9_.-]*\)\].*/\1/p' "$file"
}

_plx_recipes() {
  local home dirs=() here
  home="${PLX_HOME:-$HOME/.plx}"
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
  dirs+=("$home/recipes")
  dirs+=("$here/../examples/recipes")
  local directory file
  for directory in "${dirs[@]}"; do
    [ -d "$directory" ] || continue
    for file in "$directory"/*.toml; do
      [ -f "$file" ] || continue
      file="${file##*/}"
      printf '%s\n' "${file%.toml}"
    done
  done
}

_plx() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  local command="${COMP_WORDS[1]}"
  COMPREPLY=()

  if [ "$COMP_CWORD" -eq 1 ]; then
    _plx_complete "$_plx_commands --help --version --json --no-color --home" "$cur"
    return 0
  fi

  case "$command" in
    config)
      _plx_complete "show path init set edit" "$cur" ;;
    install)
      _plx_complete "alpine ubuntu debian kali archlinux --list --url --force --dry-run --dest --arch" "$cur" ;;
    rootfs)
      _plx_complete "status remove" "$cur" ;;
    mount)
      _plx_complete "show --engine --command" "$cur" ;;
    shell)
      _plx_complete "proot chroot --engine --root --no-login --dry-run --show -c" "$cur" ;;
    service)
      if [ "$COMP_CWORD" -eq 2 ]; then
        _plx_complete "ls status up down daemon reload example edit logs start stop restart" "$cur"
      else
        _plx_complete "$(_plx_services)" "$cur"
      fi ;;
    recipe)
      if [ "$COMP_CWORD" -eq 2 ]; then
        _plx_complete "ls show apply copy" "$cur"
      else
        _plx_complete "$(_plx_recipes)" "$cur"
      fi ;;
    hw)
      _plx_complete "ls status call battery wifi sensors location torch clipboard-get clipboard-set notification toast vibrate camera tts volume brightness wake-lock wake-unlock telephony" "$cur" ;;
    backup)
      _plx_complete "create ls verify restore prune" "$cur" ;;
    net)
      _plx_complete "ip ports ssh sshd-config doctor" "$cur" ;;
    gui)
      _plx_complete "status start stop session" "$cur" ;;
    security)
      _plx_complete "report harden --apply --dry-run" "$cur" ;;
    *)
      COMPREPLY=() ;;
  esac
  return 0
}

complete -F _plx plx
