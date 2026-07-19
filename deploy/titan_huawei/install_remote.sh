#!/usr/bin/env bash
set -euo pipefail

BASE="/home/softcup/titan"
PUBLIC_IP="139.159.150.134"
PRIVATE_IP="172.31.11.79"
PUBLIC_APP_PORT="20081"
PUBLIC_ADMIN_PORT="20082"
TURN_PORT="20083"
APP_UPSTREAM_PORT="20101"
ADMIN_UPSTREAM_PORT="20111"
TURN_MIN_PORT="20200"
TURN_MAX_PORT="20399"

if [[ "$(id -un)" != "softcup" ]]; then
  echo "This installer must run as softcup." >&2
  exit 1
fi

mkdir -p \
  "$BASE/app" \
  "$BASE/coturn/packages" \
  "$BASE/coturn/root" \
  "$BASE/runtime" \
  "$BASE/systemd" \
  "$BASE/tls"

# Refuse to claim a port that is already owned by an unrelated process. On an
# idempotent re-run, listeners owned by the two Titan units are allowed.
python3 - "$PUBLIC_APP_PORT" "$PUBLIC_ADMIN_PORT" "$TURN_PORT" \
  "$APP_UPSTREAM_PORT" "$ADMIN_UPSTREAM_PORT" "$TURN_MIN_PORT" "$TURN_MAX_PORT" <<'PY'
import subprocess
import sys

fixed = {int(value) for value in sys.argv[1:6]}
relay_min, relay_max = map(int, sys.argv[6:8])
active = any(
    subprocess.run(
        ["systemctl", "--user", "is-active", "--quiet", unit],
        check=False,
    ).returncode == 0
    for unit in ("titan-public-proxy.service", "titan-coturn.service")
)
if active:
    raise SystemExit(0)

result = subprocess.run(
    ["ss", "-H", "-lntup"],
    check=True,
    capture_output=True,
    text=True,
)
conflicts = set()
for line in result.stdout.splitlines():
    fields = line.split()
    if len(fields) < 5:
        continue
    try:
        port = int(fields[4].rsplit(":", 1)[1])
    except (ValueError, IndexError):
        continue
    if port in fixed or relay_min <= port <= relay_max:
        conflicts.add(port)
if conflicts:
    joined = ", ".join(map(str, sorted(conflicts)))
    raise SystemExit(f"Refusing to deploy: requested ports already in use: {joined}")
PY

if [[ ! -x "$BASE/coturn/root/usr/bin/turnserver" ]]; then
  cd "$BASE/coturn/packages"
  apt download \
    coturn \
    libevent-extra-2.1-7 \
    libevent-openssl-2.1-7 \
    libhiredis0.14 \
    libmysqlclient21 \
    libpq5
  for package in ./*.deb; do
    dpkg-deb -x "$package" "$BASE/coturn/root"
  done
fi

TURN_LIB="$BASE/coturn/root/usr/lib/x86_64-linux-gnu"
missing_libraries="$(
  env LD_LIBRARY_PATH="$TURN_LIB" \
    ldd "$BASE/coturn/root/usr/bin/turnserver" | awk '/not found/ {print $1}'
)"
if [[ -n "$missing_libraries" ]]; then
  echo "coturn libraries are incomplete: $missing_libraries" >&2
  exit 1
fi

if [[ ! -s "$BASE/runtime/direct.env" ]]; then
  umask 077
  turn_secret="$(openssl rand -hex 24)"
  admin_password="$(openssl rand -hex 16)"
  admin_session_secret="$(openssl rand -hex 32)"
  {
    printf "PUBLIC_APP_URL='https://%s:%s'\n" "$PUBLIC_IP" "$PUBLIC_APP_PORT"
    printf "PUBLIC_ADMIN_URL='https://%s:%s'\n" "$PUBLIC_IP" "$PUBLIC_ADMIN_PORT"
    printf "TITAN_HUAWEI_TUNNEL_AUTOSTART='true'\n"
    printf "ADMIN_REQUEST_PORT='%s'\n" "$PUBLIC_ADMIN_PORT"
    printf "ADMIN_USERNAME='admin'\n"
    printf "ADMIN_PASSWORD='%s'\n" "$admin_password"
    printf "ADMIN_SESSION_SECRET='%s'\n" "$admin_session_secret"
    printf "LOCAL_TURN_ENABLED='false'\n"
    printf "TURN_ENABLED='true'\n"
    printf "TURN_PUBLIC_HOST='%s'\n" "$PUBLIC_IP"
    # Huawei's current external security policy admits TCP but drops UDP on
    # this range. Advertise only the verified transport to avoid ICE delays.
    printf "TURN_UDP_ENABLED='false'\n"
    printf "TURN_PORT='%s'\n" "$TURN_PORT"
    printf "TURN_USERNAME='titan_webrtc'\n"
    printf "TURN_CREDENTIAL='%s'\n" "$turn_secret"
    printf "CLOUDFLARE_TURN_KEY_ID=''\n"
    printf "CLOUDFLARE_TURN_API_TOKEN=''\n"
  } > "$BASE/runtime/direct.env"
  chmod 600 "$BASE/runtime/direct.env"
fi

# shellcheck disable=SC1091
source "$BASE/runtime/direct.env"

umask 077
{
  printf 'listening-port=%s\n' "$TURN_PORT"
  printf 'listening-ip=%s\n' "$PRIVATE_IP"
  printf 'relay-ip=%s\n' "$PRIVATE_IP"
  printf 'external-ip=%s/%s\n' "$PUBLIC_IP" "$PRIVATE_IP"
  printf 'min-port=%s\n' "$TURN_MIN_PORT"
  printf 'max-port=%s\n' "$TURN_MAX_PORT"
  printf 'realm=titan.lingshan.local\n'
  printf 'server-name=titan-turn\n'
  printf 'fingerprint\n'
  printf 'lt-cred-mech\n'
  printf 'user=%s:%s\n' "$TURN_USERNAME" "$TURN_CREDENTIAL"
  printf 'stale-nonce=600\n'
  printf 'no-cli\n'
  printf 'no-tls\n'
  printf 'no-dtls\n'
  printf 'no-multicast-peers\n'
  printf 'pidfile=%s\n' "$BASE/runtime/turnserver.pid"
} > "$BASE/coturn/turnserver.conf"
chmod 600 "$BASE/coturn/turnserver.conf"

if [[ ! -s "$BASE/tls/cert.pem" || ! -s "$BASE/tls/key.pem" ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -keyout "$BASE/tls/key.pem" \
    -out "$BASE/tls/cert.pem" \
    -subj "/CN=$PUBLIC_IP/O=Titan/C=CN" \
    -addext "subjectAltName=IP:$PUBLIC_IP,DNS:lingshan.$PUBLIC_IP.sslip.io" \
    >/dev/null 2>&1
  chmod 600 "$BASE/tls/key.pem"
  chmod 644 "$BASE/tls/cert.pem"
fi

mkdir -p "$HOME/.config/systemd/user"
ln -sfn "$BASE/systemd/titan-public-proxy.service" \
  "$HOME/.config/systemd/user/titan-public-proxy.service"
ln -sfn "$BASE/systemd/titan-coturn.service" \
  "$HOME/.config/systemd/user/titan-coturn.service"

systemctl --user daemon-reload
systemctl --user enable --now titan-public-proxy.service titan-coturn.service

for unit in titan-public-proxy.service titan-coturn.service; do
  systemctl --user is-active --quiet "$unit" || {
    systemctl --user status --no-pager "$unit" >&2
    exit 1
  }
done

echo "Titan Huawei edge services are active."
