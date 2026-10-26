#!/usr/bin/env bash
# Install Linux Music RPC for the current user or system-wide.
set -euo pipefail

REPO_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
MODE="user"
ENABLE_SERVICE=0
FORCE_CONFIG=0
SKIP_DEPS=0

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Options:
  --system           Install to /usr (requires root / sudo)
  --enable-service   Enable and start the systemd user service (user mode)
  --force-config     Overwrite an existing config.ini with the example
  --skip-deps        Do not fail when playerctl is missing
  -h, --help         Show this help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --system) MODE="system" ;;
    --enable-service) ENABLE_SERVICE=1 ;;
    --force-config) FORCE_CONFIG=1 ;;
    --skip-deps) SKIP_DEPS=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

PYTHON=${PYTHON:-python3}
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Error: $PYTHON not found." >&2
  exit 1
fi
PYTHON_BIN=$(command -v "$PYTHON")

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "Error: Python 3.9 or newer is required (found $("$PYTHON_BIN" -V 2>&1))." >&2
  exit 1
fi

if ! command -v playerctl >/dev/null 2>&1; then
  echo "Warning: playerctl is not installed." >&2
  echo "  Arch:          sudo pacman -S playerctl" >&2
  echo "  Debian/Ubuntu: sudo apt install playerctl" >&2
  echo "  Fedora:        sudo dnf install playerctl" >&2
  echo "  openSUSE:      sudo zypper install playerctl" >&2
  if [ "$SKIP_DEPS" -eq 0 ]; then
    echo "Install it first, or pass --skip-deps to continue anyway." >&2
    exit 1
  fi
fi

install_user() {
  local data_root="${XDG_DATA_HOME:-$HOME/.local/share}"
  local config_root="${XDG_CONFIG_HOME:-$HOME/.config}"
  local lib_dir="$data_root/linux-music-rpc"
  local bin_dir="$HOME/.local/bin"
  local config_dir="$config_root/linux-music-rpc"
  local unit_dir="$config_root/systemd/user"

  install -d -m755 "$lib_dir" "$bin_dir"
  rm -rf "$lib_dir/music_rpc"
  cp -a "$REPO_DIR/music_rpc" "$lib_dir/"
  find "$lib_dir" -type d -name __pycache__ -prune -exec rm -rf {} +
  find "$lib_dir" -type f -name '*.pyc' -delete

  cat > "$bin_dir/linux-music-rpc" <<EOF
#!/bin/sh
PYTHONPATH="$lib_dir\${PYTHONPATH:+:\$PYTHONPATH}" exec "$PYTHON_BIN" -m music_rpc "\$@"
EOF
  chmod 755 "$bin_dir/linux-music-rpc"

  install -d -m700 "$config_dir"
  if [ ! -f "$config_dir/config.ini" ] || [ "$FORCE_CONFIG" -eq 1 ]; then
    install -m600 "$REPO_DIR/music_rpc/config.example.ini" "$config_dir/config.ini"
    echo "Config created: $config_dir/config.ini"
  else
    echo "Config kept:    $config_dir/config.ini"
  fi

  install -d -m755 "$unit_dir"
  cat > "$unit_dir/linux-music-rpc.service" <<EOF
[Unit]
Description=Linux Music RPC (MPRIS -> Discord Rich Presence)
After=graphical-session.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
ExecStart="$bin_dir/linux-music-rpc" --config "$config_dir/config.ini"
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1
NoNewPrivileges=true

[Install]
WantedBy=default.target
EOF

  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload || true
    if [ "$ENABLE_SERVICE" -eq 1 ]; then
      if grep -Eq '^[[:space:]]*client_id[[:space:]]*=[[:space:]]*[0-9]+' \
        "$config_dir/config.ini"; then
        systemctl --user enable --now linux-music-rpc.service || true
      else
        echo "Note: client_id is not set yet; enabling the service without starting it."
        systemctl --user enable linux-music-rpc.service || true
      fi
    fi
  fi

  echo
  echo "Installed to:   $lib_dir"
  echo "Launcher:       $bin_dir/linux-music-rpc"
  echo "Config:         $config_dir/config.ini"
  echo "Service:        $unit_dir/linux-music-rpc.service"
  case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *) echo
       echo "Add this to your shell profile:"
       echo "  export PATH=\"$bin_dir:\$PATH\"" ;;
  esac
  echo
  echo "Next steps:"
  echo "  1. Set [discord] client_id in $config_dir/config.ini"
  echo "  2. $bin_dir/linux-music-rpc --check"
  echo "  3. $bin_dir/linux-music-rpc --dry-run"
  echo "  4. systemctl --user enable --now linux-music-rpc.service"
}

install_system() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "Error: --system requires root. Run: sudo ./install.sh --system" >&2
    exit 1
  fi
  local lib_dir="/usr/lib/linux-music-rpc"

  install -d -m755 "$lib_dir" /usr/bin /usr/lib/systemd/user \
    /usr/share/doc/linux-music-rpc /usr/share/licenses/linux-music-rpc
  rm -rf "$lib_dir/music_rpc"
  cp -a "$REPO_DIR/music_rpc" "$lib_dir/"
  find "$lib_dir" -type d -name __pycache__ -prune -exec rm -rf {} +
  find "$lib_dir" -type f -name '*.pyc' -delete

  install -Dm755 "$REPO_DIR/packaging/launcher" /usr/bin/linux-music-rpc
  install -Dm644 "$REPO_DIR/packaging/linux-music-rpc.service" \
    /usr/lib/systemd/user/linux-music-rpc.service
  install -Dm644 "$REPO_DIR/music_rpc/config.example.ini" \
    /usr/share/doc/linux-music-rpc/config.example.ini
  install -Dm644 "$REPO_DIR/README.md" \
    /usr/share/doc/linux-music-rpc/README.md
  install -Dm644 "$REPO_DIR/LICENSE" \
    /usr/share/licenses/linux-music-rpc/LICENSE

  echo "Installed system-wide:"
  echo "  /usr/bin/linux-music-rpc"
  echo "  $lib_dir"
  echo "  /usr/lib/systemd/user/linux-music-rpc.service"
  echo
  echo "For each user:"
  echo "  linux-music-rpc --init"
  echo "  edit ~/.config/linux-music-rpc/config.ini"
  echo "  linux-music-rpc --check"
  echo "  systemctl --user enable --now linux-music-rpc.service"
  if [ "$ENABLE_SERVICE" -eq 1 ]; then
    echo
    echo "Note: --enable-service only applies to user installs."
  fi
}

case "$MODE" in
  user) install_user ;;
  system) install_system ;;
esac
