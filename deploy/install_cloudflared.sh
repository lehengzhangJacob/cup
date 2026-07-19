#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${CLOUDFLARED_INSTALL_DIR:-/home/gmn/.local/bin}"
case "$(uname -m)" in
  x86_64) asset="cloudflared-linux-amd64" ;;
  aarch64|arm64) asset="cloudflared-linux-arm64" ;;
  *)
    echo "Unsupported architecture: $(uname -m)" >&2
    exit 1
    ;;
esac

mkdir -p "$INSTALL_DIR"
download_file="$(mktemp)"
trap 'rm -f "$download_file"' EXIT
curl -fL --retry 3   "https://github.com/cloudflare/cloudflared/releases/latest/download/$asset"   -o "$download_file"
chmod 0755 "$download_file"
"$download_file" --version
install -m 0755 "$download_file" "$INSTALL_DIR/cloudflared"
echo "Installed $INSTALL_DIR/cloudflared"
