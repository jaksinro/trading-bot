#!/usr/bin/env bash
# Equivalent Linux de autostart_bots.ps1 (EF-82) : relance le serveur de
# controle puis tous les bots connus (config/*.yml). Appele par systemd au
# demarrage du Raspberry Pi, mais utilisable a la main.
#
# Meme logique que la version Windows : le serveur porte son propre verrou
# anti-doublon, l'API repond 409 pour un bot deja actif (ignore ici), et on
# attend que le serveur REPONDE plutot qu'un delai fixe.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="$ROOT/.venv/bin/python"
LOG="$ROOT/logs/autostart.log"
mkdir -p "$ROOT/logs"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }
log "Autostart declenche."

# EF-86 : si le serveur est en HTTPS (certificat dans .env), lui parler en
# HTTPS. `-k` : appel en boucle locale vers notre propre certificat
# auto-signe, il n'y a personne a authentifier entre les deux.
BASE="http://127.0.0.1:8765"
CURL=(curl -s)
if grep -q "^DASHBOARD_TLS_CERT=.\+" .env 2> /dev/null; then
    BASE="https://127.0.0.1:8765"
    CURL=(curl -s -k)
fi

# Le serveur peut deja tourner (unite systemd separee) : on ne le lance ici
# que s'il ne repond pas, sinon son verrou le refuserait de toute facon.
if ! "${CURL[@]}" -m 2 -o /dev/null "$BASE/api/list-configs"; then
    nohup "$PYTHON" -m tradingbot.control_server >> "$ROOT/logs/control_server.out" 2>&1 &
fi

ready=0
for _ in $(seq 1 60); do
    if "${CURL[@]}" -m 2 -o /dev/null "$BASE/api/list-configs"; then
        ready=1; break
    fi
    sleep 1
done
if [ "$ready" -ne 1 ]; then
    log "Serveur de controle indisponible apres 60s - abandon."
    exit 1
fi
log "Serveur de controle pret."

# Les appels partent de 127.0.0.1 : exemptes de mot de passe par le serveur.
for cfg in "$ROOT"/config/*.yml; do
    [ -e "$cfg" ] || continue
    name="config/$(basename "$cfg")"
    code=$("${CURL[@]}" -m 30 -o /dev/null -w "%{http_code}" -X POST \
        -H "Content-Type: application/json" \
        -d "{\"config_path\":\"$name\"}" "$BASE/api/start-bot")
    log "start-bot $name -> HTTP $code"
done
log "Autostart termine."
