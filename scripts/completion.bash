# bash completion for plx — source it or drop it in /usr/share/bash-completion/completions/plx
_plx_commands="version info doctor config install rootfs shell exec mount service recipe hw backup net gui security"

_plx_services() {
  local file="${PLX_HOME:-$HOME/.plx}/services.toml"
  [ -f "$file" ] && grep -oE '^\[service\.[A-Za-z0-9_.-]+\]' "$file" | sed 's/\[service\.//; s/\]//'
}

_plx_recipes() {
  local dir="${PLX_HOME:-$HOME/.plx}/recipes"
  { ls "$dir"/*.toml 2>/dev/null; ls "$(dirname "${BASH_SOURCE[0]}")/../examples/recipes"/*.toml 2>/dev/null; } \
    | xargs -r -n1 basename 2>/dev/null | sed 's/\.toml$//'
}

_plx() {
  local cur prev words cword
  _init_completion 2>/dev/null || {
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
  }
  local command="${COMP_WORDS[1]}"

  if [ "$COMP_CWORD" -eq 1 ]; then
    COMPREPLY=($(compgen -W "$_plx_commands --help --version --json --no-color --home" -- "$cur"))
    return
  fi

  case "$command" in
    config)  COMPREPLY=($(compgen -W "show path init set edit" -- "$cur")) ;;
    install) COMPREPLY=($(compgen -W "--list alpine ubuntu debian kali archlinux --url --force --dry-run --dest --arch" -- "$cur")) ;;
    rootfs)  COMPREPLY=($(compgen -W "status remove" -- "$cur")) ;;
    mount)   COMPREPLY=($(compgen -W "show --engine --command" -- "$cur")) ;;
    shell)   COMPREPLY=($(compgen -W "--engine proot chroot --root --no-login --dry-run --show -c" -- "$cur")) ;;
    service)
      if [ "$COMP_CWORD" -eq 2 ]; then
        COMPREPLY=($(compgen -W "ls status up down daemon reload example edit logs start stop restart" -- "$cur"))
      else
        COMPREPLY=($(compgen -W "$(_plx_services)" -- "$cur"))
      fi ;;
    recipe)
      if [ "$COMP_CWORD" -eq 2 ]; then
        COMPREPLY=($(compgen -W "ls show apply copy" -- "$cur"))
      else
        COMPREPLY=($(compgen -W "$(_plx_recipes)" -- "$cur"))
      fi ;;
    hw)      COMPREPLY=($(compgen -W "ls status call battery wifi sensors torch clipboard-get clipboard-set notification vibrate location camera tts volume brightness wake-lock wake-unlock" -- "$cur")) ;;
    backup)  COMPREPLY=($(compgen -W "create ls verify restore prune" -- "$cur")) ;;
    net)     COMPREPLY=($(compgen -W "ip ports ssh sshd-config doctor" -- "$cur")) ;;
    gui)     COMPREPLY=($(compgen -W "status start stop session" -- "$cur")) ;;
    security) COMPREPLY=($(compgen -W "report harden --apply --dry-run" -- "$cur")) ;;
  esac
}
complete -F _plx plx
