#!/usr/bin/env bash
# Remove Linux Music RPC.
set -euo pipefail

MODE="user"
PURGE=0

usage() {
  cat <<'EOF'
Usage: ./uninstall.sh [options]

Options:
  --system   Remove a system-wide installation (requires root)
  --purge    Also remove config and artwork cache
  -h, --help Show this help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --system) MODE="system" ;;
    --purge) PURGE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [ "$MODE" = "user" ]; then
  data_root="${XDG_DATA_HOME:-$HOME/.local/share}"
  config_root="${XDG_CONFIG_HOME:-$HOME/.config}"
  cache_root="${XDG_CACHE_HOME:-$HOME/.cache}"
  lib_dir="$data_root/linux-music-rpc"
  config_dir="$config_root/linux-music-rpc"
  unit_dir="$config_root/systemd/user"

  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now linux-music-rpc.service 2>/dev/null || true
  fi
  rm -f "$HOME/.local/bin/linux-music-rpc"
  rm -f "$unit_dir/linux-music-rpc.service"
  rm -rf "$lib_dir"
  if [ "$PURGE" -eq 1 ]; then
    rm -rf "$config_dir" "$cache_root/linux-music-rpc"
  fi
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload || true
  fi
  echo "Removed Linux Music RPC (user installation)."
  if [ "$PURGE" -eq 0 ]; then
    echo "Config kept: $config_dir/config.ini"
    echo "Use --purge to remove it and the artwork cache."
  fi
else
  if [ "$(id -u)" -ne 0 ]; then
    echo "Error: --system requires root. Run: sudo ./uninstall.sh --system" >&2
    exit 1
  fi
  rm -f /usr/bin/linux-music-rpc
  rm -f /usr/lib/systemd/user/linux-music-rpc.service
  rm -rf /usr/lib/linux-music-rpc
  rm -rf /usr/share/doc/linux-music-rpc
  rm -rf /usr/share/licenses/linux-music-rpc
  echo "Removed Linux Music RPC (system installation)."
  echo "User configs and caches were left untouched."
fi
