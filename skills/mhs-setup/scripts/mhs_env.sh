#!/usr/bin/env bash
# mhs_env.sh — idempotent, conflict-aware manager for the MHS_ env vars in
# $HERMES_HOME/.env (created if missing, chmod 600). Implements the
# read -> default -> ask -> persist contract from skills/_conventions/PORTABLE.md:
#
#   * It NEVER overwrites a value that is already present in .env (no clobber).
#   * It only APPENDS keys that are missing, so re-merging updated skills and
#     re-running setup is always safe (incremental merge).
#   * Keys the user already customized are left untouched.
#
# Usage:
#   mhs_env.sh show                    # print current MHS_* (+ plugin mirror) values
#   mhs_env.sh set KEY=value [KEY=value ...]
#       Adds/updates ONLY keys not already set; existing keys are kept (reported).
#   mhs_env.sh unset KEY [KEY ...]     # remove keys (use with care)
#
# The manager is pure bash so it runs in minimal pods (no python/php required).

set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
ENVFILE="$HERMES_HOME/.env"
# The in-repo moodle_audit_quiz plugin tool reads this un-prefixed var; mirror it.
MIRROR_KEY="MOODLE_AUDIT_CAMPUS_IPS"

ensure_envfile() {
  if [[ ! -f "$ENVFILE" ]]; then
    mkdir -p "$HERMES_HOME"
    : > "$ENVFILE"
    chmod 600 "$ENVFILE"
  fi
}

# read a key's value from .env (last occurrence wins), or "" if absent
env_get() {
  local key="$1"
  [[ -f "$ENVFILE" ]] || { printf ''; return; }
  local v
  v=$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "$ENVFILE" 2>/dev/null | tail -n1 \
      | sed -E "s/^[[:space:]]*(export[[:space:]]+)?${key}=//" \
      | sed -E "s/^\"(.*)\"$/\1/; s/^'(.*)'\$/\1/")
  printf '%s' "$v"
}

# is a key already present in .env?
env_has() {
  [[ -f "$ENVFILE" ]] || return 1
  grep -qE "^[[:space:]]*(export[[:space:]]+)?$1=" "$ENVFILE" 2>/dev/null
}

cmd_show() {
  ensure_envfile
  echo "# $ENVFILE"
  if [[ -f "$ENVFILE" ]]; then
    grep -E "^[[:space:]]*(export[[:space:]]+)?(MHS_|${MIRROR_KEY})=" "$ENVFILE" 2>/dev/null \
      || echo "(no MHS_ vars set yet)"
  fi
}

cmd_set() {
  ensure_envfile
  local written=0 kept=0
  for pair in "$@"; do
    local k="${pair%%=*}" v="${pair#*=}"
    if env_has "$k"; then
      # conflict-aware: never clobber an existing value
      printf '  keep   %-22s = %s   (already set; not overwritten)\n' "$k" "$(env_get "$k")"
      kept=$((kept+1))
      continue
    fi
    printf 'export %s=%s\n' "$k" "$v" >> "$ENVFILE"
    printf '  set    %-22s = %s\n' "$k" "$v"
    written=$((written+1))
  done
  # mirror campus CIDR into the plugin's un-prefixed var (only if not already set)
  local campus
  campus="$(env_get MHS_CAMPUS_CIDR)"
  if [[ -n "$campus" ]] && ! env_has "$MIRROR_KEY"; then
    printf 'export %s=%s\n' "$MIRROR_KEY" "$campus" >> "$ENVFILE"
    printf '  set    %-22s = %s   (mirror of MHS_CAMPUS_CIDR)\n' "$MIRROR_KEY" "$campus"
    written=$((written+1))
  fi
  chmod 600 "$ENVFILE"
  printf '\nset=%s kept=%s  -> %s\n' "$written" "$kept" "$ENVFILE"
}

cmd_unset() {
  ensure_envfile
  local removed=0
  for k in "$@"; do
    if env_has "$k"; then
      # rewrite .env without the key lines
      local tmp
      tmp="$(mktemp)"
      grep -vE "^[[:space:]]*(export[[:space:]]+)?${k}=" "$ENVFILE" > "$tmp" || true
      mv "$tmp" "$ENVFILE"
      chmod 600 "$ENVFILE"
      printf '  unset  %s\n' "$k"
      removed=$((removed+1))
    fi
  done
  printf 'removed=%s\n' "$removed"
}

case "${1:-}" in
  show)   cmd_show ;;
  set)    shift; cmd_set "$@" ;;
  unset)  shift; cmd_unset "$@" ;;
  *)
    echo "usage: mhs_env.sh show | set KEY=value [...] | unset KEY [...]" >&2
    exit 2
    ;;
esac
