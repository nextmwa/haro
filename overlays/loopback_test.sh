#!/bin/bash
# Registra qualche secondo dal microfono e lo riproduce subito sulla cassa,
# bypassando wake word e server AI -- serve solo a verificare ad orecchio
# che mic e amplificatore funzionino bene insieme sull'overlay haro-duplex.
set -euo pipefail

DURATION="${1:-4}"
OUT=/tmp/haro-loopback.wav

WAS_ACTIVE=false
if systemctl is-active --quiet haro.service; then
    WAS_ACTIVE=true
    echo "Fermo haro.service (mi serve il microfono libero)..."
    sudo systemctl stop haro.service
fi
restore_service() {
    if [ "$WAS_ACTIVE" = true ]; then
        echo "Riavvio haro.service..."
        sudo systemctl start haro.service
    fi
}
trap restore_service EXIT

echo "Registro per ${DURATION}s -- PARLA ORA vicino al microfono."
arecord -D hw:haroduplex,1 -f S32_LE -r 16000 -c 2 -d "$DURATION" "$OUT"

echo "Riproduco quello che ho registrato..."
aplay -D hw:haroduplex,0 "$OUT"

echo "Fatto. Hai sentito la tua voce chiara dalla cassa? Se sì, mic+cassa funzionano."
