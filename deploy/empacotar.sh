#!/usr/bin/env bash
# Corre no teu PC. Cria bigodds.tar.gz com a app e os dados (apostas, modelos, árbitros) para enviar para a máquina.
#   ./empacotar.sh            app + dados (primeira instalação)
#   ./empacotar.sh --codigo   só o código (atualizações: não mexe nas tuas apostas na máquina)
set -euo pipefail
cd "$(dirname "$0")/.."
out="deploy/bigodds.tar.gz"
excl=(--exclude='__pycache__' --exclude='app/fixtures.csv' --exclude='app/data/espn/sum_*' --exclude='app/data/espn/pre_*' --exclude='app/data/espn/meteo_*' --exclude='app/data/espn/uefa_*' --exclude='app/data/espn/sched_*' --exclude='app/data/espn/estadios.json')  # leva só os jogos europeus com resultados (uefa2_*), que o Elo usa
if [[ "${1:-}" == "--codigo" ]]; then
  excl+=(--exclude='app/data/apostas.sqlite' --exclude='app/data/ntfy*.json' --exclude='app/data/notas.json')
  tar czf "$out" "${excl[@]}" app/*.py app/web deploy/instalar.sh deploy/bigodds.service
else
  tar czf "$out" "${excl[@]}" app data/arbitros/*.csv deploy/instalar.sh deploy/bigodds.service
fi
echo "Pronto: $out ($(du -h "$out" | cut -f1)). Envia-o para a máquina e corre: sudo bash instalar.sh"
