#!/bin/bash
# Uzak repoda yeni commit varsa otomatik git pull yapar.

git fetch origin main 2>/dev/null

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "[guncelle] Kod guncel, pull gerekmez."
else
    echo "[guncelle] Yeni guncelleme bulundu, cekiliyor..."
    git pull origin main
    echo "[guncelle] Tamamlandi."
fi
