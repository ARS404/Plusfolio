#!/bin/sh
# Run once on a fresh Debian/Ubuntu VPS, then answer the setup prompts.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if ! command -v python3 >/dev/null 2>&1 || ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1 || ! docker buildx version >/dev/null 2>&1; then
  if [ "$(id -u)" != 0 ]; then echo 'For first installation run: sudo bash scripts/install_server.sh'; exit 1; fi
  . /etc/os-release
  case "$ID" in ubuntu|debian) ;; *) echo 'Install Docker Engine + Compose and Python 3, then run python3 scripts/server.py init'; exit 1;; esac
  apt-get update
  apt-get install -y ca-certificates curl python3
  install -m 0755 -d /etc/apt/keyrings
  curl --fail --silent --show-error "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' "$(dpkg --print-architecture)" "$ID" "$VERSION_CODENAME" > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi
exec python3 scripts/server.py init "$@"
