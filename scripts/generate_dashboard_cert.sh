#!/usr/bin/env bash
# Genere un certificat HTTPS auto-signe pour le dashboard (EF-86).
#
#   bash scripts/generate_dashboard_cert.sh            # IP locales detectees
#   bash scripts/generate_dashboard_cert.sh 192.168.1.42 monpi.local
#
# Ecrit certs/dashboard.crt et certs/dashboard.key (dossier ignore par git),
# puis indique les deux lignes a ajouter dans .env. Le certificat couvre
# localhost, le nom de la machine, ses IP locales et les noms/IP passes en
# argument - un appareil qui ouvre le dashboard par une adresse absente du
# certificat affichera un avertissement.
#
# Auto-signe = le navigateur previent une premiere fois ("connexion non
# privee") : c'est attendu, il suffit d'accepter l'exception sur chaque
# appareil. Le chiffrement, lui, est reel des la premiere connexion.
# Ne remplace pas un certificat existant : supprimer certs/ pour regenerer.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
CERT="certs/dashboard.crt"
KEY="certs/dashboard.key"

command -v openssl > /dev/null || { echo "openssl introuvable (sudo apt-get install openssl)"; exit 1; }
if [ -f "$CERT" ] && [ -f "$KEY" ]; then
    echo "Certificat deja present : $CERT (supprimer certs/ pour le regenerer)."
else
    mkdir -p certs
    HOST="$(hostname)"
    SAN="DNS:localhost,DNS:$HOST,DNS:$HOST.local,IP:127.0.0.1,IP:::1"
    for ip in $(hostname -I 2>/dev/null || true); do
        SAN="$SAN,IP:$ip"
    done
    for extra in "$@"; do
        if [[ "$extra" =~ ^[0-9.]+$ || "$extra" == *:* ]]; then
            SAN="$SAN,IP:$extra"
        else
            SAN="$SAN,DNS:$extra"
        fi
    done
    # 10 ans : un certificat maison qui expire casse le dashboard sans prevenir.
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
        -keyout "$KEY" -out "$CERT" -days 3650 \
        -subj "/CN=$HOST" -addext "subjectAltName=$SAN"
    chmod 600 "$KEY"
    echo "Certificat cree pour : $SAN"
fi

echo
echo "Ajoute (ou decommente) dans .env, puis relance le serveur :"
echo "  DASHBOARD_TLS_CERT=certs/dashboard.crt"
echo "  DASHBOARD_TLS_KEY=certs/dashboard.key"
