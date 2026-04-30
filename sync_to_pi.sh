#!/usr/bin/env bash
# =============================================================================
# sync_to_pi.sh — Bu makineden Raspberry Pi'ye otomatik rsync
#
# Kullanim:
#   ./sync_to_pi.sh           # degisikleri Pi'ye gonder
#   ./sync_to_pi.sh --watch   # surekli izle, degisiklikte otomatik gonder
#   ./sync_to_pi.sh --dry     # ne gonderilecegini goster, gonderme
#   ./sync_to_pi.sh --reset   # konfigurasyonu sifirla (yeniden sor)
# =============================================================================

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CONFIG_FILE="$SCRIPT_DIR/.syncconfig"

# --- Konfigurasyon yukle veya ilk kurulum -----------------------------------
if [ "$1" == "--reset" ] || [ ! -f "$CONFIG_FILE" ]; then
    echo "=========================================="
    echo "  Pi rsync ilk kurulum"
    echo "=========================================="
    read -p "Pi kullanicisi (varsayilan: pi): " PI_USER
    PI_USER=${PI_USER:-pi}

    read -p "Pi adresi (orn: raspberrypi.local veya 192.168.1.50): " PI_HOST
    if [ -z "$PI_HOST" ]; then
        echo "HATA: Pi adresi girilmedi."
        exit 1
    fi

    read -p "Pi'deki proje yolu (varsayilan: /home/$PI_USER/ototot): " PI_PATH
    PI_PATH=${PI_PATH:-/home/$PI_USER/ototot}

    cat > "$CONFIG_FILE" <<EOF
PI_USER=$PI_USER
PI_HOST=$PI_HOST
PI_PATH=$PI_PATH
EOF
    echo ""
    echo "Konfigurasyon kaydedildi: $CONFIG_FILE"
    echo ""

    # SSH key kontrol — sifresiz baglanti tavsiye et
    if ! ssh -o BatchMode=yes -o ConnectTimeout=3 "$PI_USER@$PI_HOST" exit 2>/dev/null; then
        echo "Ipucu: Sifresiz baglanti icin:"
        echo "    ssh-keygen -t ed25519   # bir kez (sifre BOS)"
        echo "    ssh-copy-id $PI_USER@$PI_HOST"
        echo ""
    fi

    [ "$1" == "--reset" ] && exit 0
fi

# shellcheck source=/dev/null
source "$CONFIG_FILE"

# --- rsync komutunu kur ------------------------------------------------------
RSYNC_OPTS=(
    -avz                    # arsiv + verbose + sikistir
    --delete                # Pi'de olup burada olmayan dosyalari sil
    --human-readable
    --exclude='.git/'
    --exclude='__pycache__/'
    --exclude='*.pyc'
    --exclude='.venv/'
    --exclude='venv/'
    --exclude='*.log'
    --exclude='frame_logs/'
    --exclude='error_log.csv'
    --exclude='.syncconfig'
)

if [ "$1" == "--dry" ]; then
    RSYNC_OPTS+=(--dry-run)
    echo "[dry-run] Sadece simulasyon — gercek transfer YOK"
fi

# --- Bir kerelik sync --------------------------------------------------------
do_sync() {
    echo "[$(date +%H:%M:%S)] $PI_USER@$PI_HOST:$PI_PATH -> sync..."
    rsync "${RSYNC_OPTS[@]}" \
        "$SCRIPT_DIR/" \
        "$PI_USER@$PI_HOST:$PI_PATH/"
    echo "[$(date +%H:%M:%S)] ✓ Tamam"
}

# --- Watch modu (otomatik) ---------------------------------------------------
if [ "$1" == "--watch" ]; then
    if ! command -v inotifywait &>/dev/null; then
        echo "HATA: inotifywait gerekli. Kur: sudo apt install inotify-tools"
        exit 1
    fi
    echo "WATCH modu — Ctrl+C ile cik"
    do_sync
    while inotifywait -qq -r -e modify,create,delete,move \
        --exclude '(\.git|__pycache__|\.pyc$|\.venv|frame_logs)' \
        "$SCRIPT_DIR"; do
        sleep 0.3   # debounce
        do_sync
    done
else
    do_sync
fi
