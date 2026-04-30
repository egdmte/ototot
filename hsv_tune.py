#!/usr/bin/env python3
# =============================================================================
# hsv_tune.py  —  HSV aralığı ayarlama aracı
#
# Canlı kamera görüntüsünde bir rengi (beyaz şerit, kırmızı/yeşil ışık,
# turuncu araç, vb.) izole etmek için doğru HSV aralığını bulur.
# Slider'ları hareket ettir → maske önizlemesini gör → değerleri kopyala.
#
# Kullanım:
#   python hsv_tune.py
#
# 'q' → çık ve değerleri yazdır
# =============================================================================
import cv2
import numpy as np
import time

try:
    from picamera2 import Picamera2
    _USE_PI = True
except ImportError:
    _USE_PI = False

from config import WIDTH, HEIGHT


def nothing(_): pass


def main():
    # Kamera başlat
    if _USE_PI:
        cam = Picamera2()
        cam.configure(cam.create_preview_configuration(
            main={"size": (WIDTH, HEIGHT), "format": "RGB888"}
        ))
        cam.start()
        time.sleep(2)
    else:
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)

    # Slider penceresi
    cv2.namedWindow("HSV Ayar")
    cv2.createTrackbar("H Min", "HSV Ayar",   0,  180, nothing)
    cv2.createTrackbar("H Max", "HSV Ayar", 180,  180, nothing)
    cv2.createTrackbar("S Min", "HSV Ayar",   0,  255, nothing)
    cv2.createTrackbar("S Max", "HSV Ayar", 255,  255, nothing)
    cv2.createTrackbar("V Min", "HSV Ayar",   0,  255, nothing)
    cv2.createTrackbar("V Max", "HSV Ayar", 255,  255, nothing)

    # Ön ayarlı profiller — 'p' tuşuyla geç
    PROFILES = {
        "beyaz_serit":    (0,   0,  140, 180,  80, 255),
        "kirmizi_isik1":  (0, 120,   80,  10, 255, 255),
        "kirmizi_isik2":  (160, 120, 80, 180, 255, 255),
        "yesil_isik":     (40,  80,  60,  90, 255, 255),
        "turuncu_arac":   (5,  140,  80,  25, 255, 255),
        "sifirla":        (0,    0,   0, 180, 255, 255),
    }
    profile_keys = list(PROFILES.keys())
    profile_idx  = 0

    def apply_profile(name):
        h1, s1, v1, h2, s2, v2 = PROFILES[name]
        cv2.setTrackbarPos("H Min", "HSV Ayar", h1)
        cv2.setTrackbarPos("H Max", "HSV Ayar", h2)
        cv2.setTrackbarPos("S Min", "HSV Ayar", s1)
        cv2.setTrackbarPos("S Max", "HSV Ayar", s2)
        cv2.setTrackbarPos("V Min", "HSV Ayar", v1)
        cv2.setTrackbarPos("V Max", "HSV Ayar", v2)
        print(f"[Profil] {name} yüklendi")

    print("Kontroller:")
    print("  'p' → sonraki ön ayar profili")
    print("  's' → mevcut değerleri kaydet")
    print("  'q' → çık")
    print(f"\nMevcut profil: {profile_keys[profile_idx]}")

    saved: list = []

    try:
        while True:
            # Kare al
            if _USE_PI:
                frame_rgb = cam.capture_array()
                frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            else:
                ret, frame = cap.read()
                if not ret:
                    continue
                frame = cv2.resize(frame, (WIDTH, HEIGHT))

            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

            # Slider değerleri oku
            h_lo = cv2.getTrackbarPos("H Min", "HSV Ayar")
            h_hi = cv2.getTrackbarPos("H Max", "HSV Ayar")
            s_lo = cv2.getTrackbarPos("S Min", "HSV Ayar")
            s_hi = cv2.getTrackbarPos("S Max", "HSV Ayar")
            v_lo = cv2.getTrackbarPos("V Min", "HSV Ayar")
            v_hi = cv2.getTrackbarPos("V Max", "HSV Ayar")

            lower = np.array([h_lo, s_lo, v_lo], dtype=np.uint8)
            upper = np.array([h_hi, s_hi, v_hi], dtype=np.uint8)
            mask  = cv2.inRange(hsv, lower, upper)

            # Yan yana göster: orijinal | maske | renkli maske
            colored_mask = cv2.bitwise_and(frame, frame, mask=mask)
            mask_bgr     = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)

            # Piksel sayısı
            px_count = int(mask.sum() / 255)
            cv2.putText(frame, f"H:{h_lo}-{h_hi} S:{s_lo}-{s_hi} V:{v_lo}-{v_hi}",
                        (5, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 230, 230), 2)
            cv2.putText(frame, f"Beyaz piksel: {px_count}",
                        (5, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

            display = np.hstack([
                cv2.resize(frame,         (WIDTH // 2, HEIGHT // 2)),
                cv2.resize(mask_bgr,      (WIDTH // 2, HEIGHT // 2)),
            ])
            display2 = np.hstack([
                cv2.resize(colored_mask,  (WIDTH // 2, HEIGHT // 2)),
                np.zeros((HEIGHT // 2, WIDTH // 2, 3), dtype=np.uint8),
            ])
            cv2.imshow("HSV Ayar", np.vstack([display, display2]))

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('p'):
                profile_idx = (profile_idx + 1) % len(profile_keys)
                apply_profile(profile_keys[profile_idx])
            elif key == ord('s'):
                entry = {
                    "isim": profile_keys[profile_idx],
                    "alt": (h_lo, s_lo, v_lo),
                    "ust": (h_hi, s_hi, v_hi),
                }
                saved.append(entry)
                print(f"[Kaydedildi] ({h_lo},{s_lo},{v_lo}) → ({h_hi},{s_hi},{v_hi})")

    finally:
        if _USE_PI:
            cam.stop()
        else:
            cap.release()
        cv2.destroyAllWindows()

    # Sonuçları yazdır
    print("\n" + "="*50)
    print("KAYDEDİLEN HSV ARALIKLARINI config.py'YE YAPISTIR:")
    print("="*50)
    for s in saved:
        print(f"\n# {s['isim']}")
        print(f"# ALT = {s['alt']}")
        print(f"# ÜST = {s['ust']}")

    if not saved:
        # En son slider değerlerini yazdır
        print(f"\nSon değerler (kaydetmedin ama bunları kullanabilirsin):")
        h_lo = cv2.getTrackbarPos("H Min", "HSV Ayar") if False else h_lo
        print(f"  ALT = ({h_lo}, {s_lo}, {v_lo})")
        print(f"  ÜST = ({h_hi}, {s_hi}, {v_hi})")


if __name__ == "__main__":
    main()
