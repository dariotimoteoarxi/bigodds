#!/usr/bin/env bash
# Corre na máquina do Google Cloud (Ubuntu 24.04), na pasta onde está o bigodds.tar.gz:  sudo bash instalar.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Corre com sudo: sudo bash instalar.sh"; exit 1; }
tarball="$(dirname "$0")/bigodds.tar.gz"
[[ -f "$tarball" ]] || tarball="./bigodds.tar.gz"
[[ -f "$tarball" ]] || { echo "Não encontrei bigodds.tar.gz nesta pasta."; exit 1; }

apt-get update -qq
apt-get install -y -qq python3 tzdata >/dev/null
timedatectl set-timezone Europe/Lisbon || true
id bigodds &>/dev/null || useradd --system --create-home --home-dir /opt/bigodds --shell /usr/sbin/nologin bigodds

mkdir -p /opt/bigodds
[[ -f /opt/bigodds/app/data/apostas.sqlite ]] && cp /opt/bigodds/app/data/apostas.sqlite "/opt/bigodds/apostas-$(date +%Y%m%d-%H%M).sqlite"  # cópia de segurança
tar xzf "$tarball" -C /opt/bigodds
chown -R bigodds:bigodds /opt/bigodds

install -m 644 /opt/bigodds/deploy/bigodds.service /etc/systemd/system/bigodds.service
systemctl daemon-reload
systemctl enable --now bigodds
systemctl restart bigodds
sleep 3
if curl -fsS -o /dev/null http://127.0.0.1:8765/; then echo "Bigodds a correr em http://127.0.0.1:8765"; else echo "O Bigodds não arrancou. Vê: journalctl -u bigodds -n 50"; exit 1; fi

if ! command -v tailscale >/dev/null; then
  echo "A instalar o Tailscale (acesso privado pelo telemóvel)..."
  curl -fsSL https://tailscale.com/install.sh | sh
fi
echo
echo "Falta ligar o Tailscale (só da primeira vez):"
echo "  1) sudo tailscale up        -> abre o link que aparece e entra com a tua conta"
echo "  2) sudo tailscale serve --bg 8765"
echo "Depois abre no telemóvel o endereço https://...ts.net que o passo 2 mostrar."
