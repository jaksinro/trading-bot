#!/usr/bin/env bash
# Installation sur Raspberry Pi (Raspberry Pi OS 64 bits / Debian) - EF-82.
#
#   git clone https://github.com/jaksinro/trading-bot.git && cd trading-bot
#   cp .env.example .env && nano .env      # cles testnet + DASHBOARD_PASSWORD
#   bash scripts/install_pi.sh
#
# Idempotent : relancer le script ne casse rien. Aucun `sudo` sauf pour
# apt et l'installation des unites systemd.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(id -un)"
cd "$ROOT"

echo "== 1/5 Paquets systeme"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip curl git

echo "== 2/5 Environnement Python"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e .

echo "== 3/5 Fichier .env"
if [ ! -f .env ]; then
    cp .env.example .env
    echo "   .env cree depuis .env.example : renseigne les cles testnet et DASHBOARD_PASSWORD, puis relance."
    exit 1
fi
if ! grep -q "^DASHBOARD_PASSWORD=.\+" .env; then
    echo "   ATTENTION : DASHBOARD_PASSWORD absent de .env - le dashboard refusera les autres appareils (403)."
fi
SCHEME="http"
if grep -q "^DASHBOARD_TLS_CERT=.\+" .env; then
    SCHEME="https"
else
    echo "   Conseil : sans HTTPS, le mot de passe circule en clair sur le reseau local."
    echo "   bash scripts/generate_dashboard_cert.sh puis ajouter DASHBOARD_TLS_CERT/KEY dans .env (EF-86)."
fi

echo "== 4/5 Tests (rapide sanity check)"
.venv/bin/python -m pytest -q tests/test_process_lock.py tests/test_control_server.py 2>&1 | tail -1

echo "== 5/5 Services systemd"
chmod +x scripts/autostart_bots.sh
for unit in tradingbot-server tradingbot-bots; do
    sed -e "s#__ROOT__#$ROOT#g" -e "s#__USER__#$USER_NAME#g" \
        "scripts/systemd/$unit.service" | sudo tee "/etc/systemd/system/$unit.service" > /dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable tradingbot-server.service tradingbot-bots.service
sudo systemctl restart tradingbot-server.service
sleep 3
sudo systemctl start tradingbot-bots.service

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "Termine. Dashboard : $SCHEME://${IP:-<ip-du-pi>}:8765/dashboard.html"
echo "Journal serveur : journalctl -u tradingbot-server -f"
echo "Journal bots    : $ROOT/logs/autostart.log"
