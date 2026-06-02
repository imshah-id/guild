#!/usr/bin/env bash
# Install guild as a user-local CLI, pipx first and pip --user as a fallback.
#
# Common use:
#   curl -fsSL https://raw.githubusercontent.com/imshah-id/guild/main/install.sh | bash
#
# From a checkout:
#   bash install.sh

set -euo pipefail

DEFAULT_REPO_URL="https://github.com/imshah-id/guild.git"

repo_url="${GUILD_REPO_URL:-$DEFAULT_REPO_URL}"
ref="${GUILD_REF:-main}"
method="${GUILD_INSTALL_METHOD:-auto}"
source_dir=""

usage() {
  cat <<'EOF'
Install guild.

Usage:
  bash install.sh [options]
  curl -fsSL https://raw.githubusercontent.com/imshah-id/guild/main/install.sh | bash

Options:
  --repo URL       Git repository to install from
  --ref REF        Git branch, tag, or commit to install (default: main)
  --local PATH     Install from a local checkout
  --method METHOD  auto, pipx, or pip-user (default: auto)
  -h, --help       Show this help

Environment:
  GUILD_REPO_URL
  GUILD_REF
  GUILD_INSTALL_METHOD
EOF
}

log() {
  printf 'guild install: %s\n' "$*" >&2
}

die() {
  printf 'guild install: error: %s\n' "$*" >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo)
      [ "$#" -ge 2 ] || die "--repo needs a value"
      repo_url="$2"
      shift 2
      ;;
    --ref)
      [ "$#" -ge 2 ] || die "--ref needs a value"
      ref="$2"
      shift 2
      ;;
    --local)
      [ "$#" -ge 2 ] || die "--local needs a value"
      source_dir="$2"
      shift 2
      ;;
    --method)
      [ "$#" -ge 2 ] || die "--method needs a value"
      method="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

case "$method" in
  auto|pipx|pip-user) ;;
  *) die "--method must be auto, pipx, or pip-user" ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
  die "python3 is required (guild needs Python 3.10+)"
fi

python3 - <<'PY' || die "Python 3.10 or newer is required"
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY

script_path="${BASH_SOURCE[0]:-$0}"
script_dir=""
if [ -n "$script_path" ] && [ -f "$script_path" ]; then
  script_dir="$(CDPATH= cd -- "$(dirname -- "$script_path")" && pwd)"
fi

if [ -z "$source_dir" ] && [ -n "$script_dir" ] && [ -f "$script_dir/pyproject.toml" ]; then
  source_dir="$script_dir"
fi

if [ -n "$source_dir" ]; then
  [ -f "$source_dir/pyproject.toml" ] || die "no pyproject.toml found in $source_dir"
  package_spec="$source_dir"
  log "installing from local checkout: $source_dir"
else
  package_spec="git+$repo_url@$ref"
  log "installing from $repo_url at $ref"
fi

install_with_pipx() {
  command -v pipx >/dev/null 2>&1 || return 1
  log "using pipx"
  pipx install --force "$package_spec"
}

install_with_pip_user() {
  log "using python3 -m pip --user"
  python3 -m pip install --user --upgrade "$package_spec"
}

case "$method" in
  pipx)
    install_with_pipx || die "pipx is not installed; rerun with --method pip-user or install pipx"
    ;;
  pip-user)
    install_with_pip_user
    ;;
  auto)
    if ! install_with_pipx; then
      install_with_pip_user
    fi
    ;;
esac

user_base="$(python3 -m site --user-base 2>/dev/null || true)"
user_bin="${user_base:+$user_base/bin}"

if command -v guild >/dev/null 2>&1; then
  log "installed: $(command -v guild)"
  guild --version || true
else
  log "installed, but 'guild' is not on PATH yet"
  if [ -n "$user_bin" ]; then
    log "add this to your shell profile if needed:"
    log "  export PATH=\"$user_bin:\$PATH\""
  fi
fi

log "done"
