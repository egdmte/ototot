#!/usr/bin/env python3
# =============================================================================
# hsv_calibrate_roi.py  —  Manuel ROI tabanlı HSV kalibrasyonu
#
# YARIŞ ÖNCESİ KULLANIM:
#   1. Aracı piste koy, kamerasını şeride doğrult.
#   2. Bu aracı çalıştır:    python hsv_calibrate_roi.py
#   3. Fareyle BEYAZ ŞERİDİN üzerine 4-5 dikdörtgen çiz.
#      (Farklı ışık/gölge alan yerlerden örnek topla — daha sağlam sonuç!)
#   4. SPACE   → mevcut ROI'yi onayla (örnek havuzuna ekle)
#      Z       → son ROI'yi geri al
#      R       → tüm ROI'leri sıfırla
#      C       → istatistikleri konsola yazdır (kaydetmeden)
#      S       → config.py'ye kaydet ve USE_MANUAL_HSV=True yap
#      Q / Esc → çık
#
# YÖNTEM:
#   • Tüm ROI'lerden binlerce piksel toplanır
#   • H, S, V kanalları için %5 ve %95 persentilleri hesaplanır
#     → uçtaki gürültü/aykırı değerler matematiksel olarak elenir
#   • Sonuç doğrudan config.py'ye yazılır → lane.py otomatik kullanır
# =============================================================================
import argparse
import os
import re
import sys
import time

import cv2
import numpy as np

# Kamera: Pi'de picamera2, geliştirme için OpenCV
try:
    from picamera2 import Picamera2
    _USE_PICAMERA = True
except ImportError:
    _USE_PICAMERA = False
    print("[kalibrasyon] picamera2 yok — OpenCV VideoCapture kullanılıyor")

from config import WIDTH, HEIGHT, CAMERA_BGR_OUTPUT, CAMERA_ROTATE_180


# ─── Konfigürasyon ───────────────────────────────────────────────────────────
PERCENTILE_LOW  = 5      # alt persentil — siyah zemin sıyrıkları atılır
PERCENTILE_HIGH = 95     # üst persentil — spot yansımalar atılır
MIN_SAMPLES     = 1000   # bu kadar piksel altında stabil sonuç vermez
MARGIN_V_LOW    = 10     # V alt sınırına ek pay (-)
MARGIN_S_HIGH   = 15     # S üst sınırına ek pay (+)

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.py')


# ─── Kamera arabirimi ─────────────────────────────────────────────────────────
class Camera:
    """Kamera kapsayıcısı — Pi/USB."""
    def __init__(self):
        if _USE_PICAMERA:
            self.cam = Picamera2()
            self.cam.configure(self.cam.create_preview_configuration(
                main={"size": (WIDTH, HEIGHT), "format": "RGB888"}
            ))
            self.cam.start()
            time.sleep(1.0)
        else:
            self.cam = cv2.VideoCapture(0)
            self.cam.set(cv2.CAP_PROP_FRAME_WIDTH,  WIDTH)
            self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)

    def capture(self) -> np.ndarray:
        if _USE_PICAMERA:
            f = self.cam.capture_array()
            if f.ndim == 3 and f.shape[2] == 4:
                f = f[:, :, :3]
            if CAMERA_BGR_OUTPUT:
                f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
        else:
            ret, f = self.cam.read()
            if not ret:
                return np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
            f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)

        # 180 derece dondur (ters montaj icin)
        if CAMERA_ROTATE_180:
            f = cv2.rotate(f, cv2.ROTATE_180)
        return f  # RGB

    def close(self):
        try:
            if _USE_PICAMERA:
                self.cam.stop()
            else:
                self.cam.release()
        except Exception:
            pass


# ─── Config yazıcı ────────────────────────────────────────────────────────────
def write_cfg(key: str, value) -> bool:
    """config.py'deki bir parametrenin değerini günceller (yorumu korur)."""
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
        pattern = rf'^({re.escape(key)}\s*=\s*)([^\n#]*)([ \t]*#[^\n]*)?'
        def replacer(m):
            comment = m.group(3) or ''
            # Comment varsa, değer ile arasına en az 2 boşluk koy
            sep = '  ' if comment and not comment.startswith((' ', '\t')) else ''
            return f"{m.group(1)}{repr(value)}{sep}{comment}"
        new_content, n = re.subn(pattern, replacer, content,
                                  flags=re.MULTILINE, count=1)
        if n == 0:
            # Anahtar bulunamadı → dosya sonuna ekle
            new_content = content.rstrip() + f"\n{key} = {repr(value)}\n"
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    except Exception as e:
        print(f"[kalibrasyon] config.py yazma hatası ({key}): {e}")
        return False


# ─── ROI yöneticisi ───────────────────────────────────────────────────────────
class ROIManager:
    """Çizilen dikdörtgenleri tutar; HSV örneklerini biriktirir."""

    def __init__(self):
        self.rects: list[tuple[int, int, int, int]] = []   # (x1, y1, x2, y2)
        # Çizim durumu
        self.drawing = False
        self.start_pt: tuple[int, int] | None = None
        self.cur_pt:   tuple[int, int] | None = None

    def on_mouse(self, event, x, y, flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.drawing = True
            self.start_pt = (x, y)
            self.cur_pt   = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and self.drawing:
            self.cur_pt = (x, y)
        elif event == cv2.EVENT_LBUTTONUP and self.drawing:
            self.drawing = False
            x1, y1 = self.start_pt
            x2, y2 = (x, y)
            x1, x2 = sorted((x1, x2))
            y1, y2 = sorted((y1, y2))
            if (x2 - x1) >= 5 and (y2 - y1) >= 5:
                self.rects.append((x1, y1, x2, y2))
                print(f"[kalibrasyon] ROI #{len(self.rects)} eklendi: "
                      f"({x1},{y1})→({x2},{y2})  alan={(x2-x1)*(y2-y1)}px²")
            self.start_pt = None
            self.cur_pt   = None

    def undo(self) -> None:
        if self.rects:
            removed = self.rects.pop()
            print(f"[kalibrasyon] Son ROI silindi: {removed}")

    def clear(self) -> None:
        self.rects.clear()
        print("[kalibrasyon] Tüm ROI'ler silindi")

    def collect_pixels(self, hsv_frame: np.ndarray) -> np.ndarray:
        """Tüm onaylı ROI'lerden HSV piksellerini topla."""
        chunks = []
        for (x1, y1, x2, y2) in self.rects:
            sub = hsv_frame[y1:y2, x1:x2]
            chunks.append(sub.reshape(-1, 3))
        if not chunks:
            return np.empty((0, 3), dtype=np.uint8)
        return np.concatenate(chunks, axis=0)


# ─── İstatistik / persentil hesabı ────────────────────────────────────────────
def compute_hsv_bounds(samples: np.ndarray) -> tuple[tuple, tuple, dict] | None:
    """Toplanan örneklerden persentil tabanlı HSV alt/üst sınırlarını hesaplar.

    Döner: (low_tuple, high_tuple, stats_dict) ya da None (yetersiz veri).
    """
    if samples.shape[0] < MIN_SAMPLES:
        return None

    H = samples[:, 0].astype(np.int32)
    S = samples[:, 1].astype(np.int32)
    V = samples[:, 2].astype(np.int32)

    # Persentiller — uçtaki gürültü atılır
    h_lo = int(np.percentile(H, PERCENTILE_LOW))
    h_hi = int(np.percentile(H, PERCENTILE_HIGH))
    s_lo = int(np.percentile(S, PERCENTILE_LOW))
    s_hi = int(np.percentile(S, PERCENTILE_HIGH))
    v_lo = int(np.percentile(V, PERCENTILE_LOW))
    v_hi = int(np.percentile(V, PERCENTILE_HIGH))

    # Beyaz şerit için akıllı sınır:
    # - H = tüm tonlar (beyaz renksiz)
    # - S = düşük olmalı (beyaz az doygun) → üst sınır + marj
    # - V = yüksek olmalı (beyaz parlak) → alt sınır - marj
    low  = (0, 0, max(0, v_lo - MARGIN_V_LOW))
    high = (180, min(255, s_hi + MARGIN_S_HIGH), 255)

    stats = {
        'samples':  int(samples.shape[0]),
        'h_range':  (h_lo, h_hi),
        's_range':  (s_lo, s_hi),
        'v_range':  (v_lo, v_hi),
        'h_mean':   float(np.mean(H)),
        's_mean':   float(np.mean(S)),
        'v_mean':   float(np.mean(V)),
        'h_std':    float(np.std(H)),
        's_std':    float(np.std(S)),
        'v_std':    float(np.std(V)),
    }
    return low, high, stats


def print_stats(low, high, stats) -> None:
    print()
    print("══════════════════════════════════════════════════════")
    print("       MANUEL HSV KALİBRASYONU — SONUÇ                ")
    print("══════════════════════════════════════════════════════")
    print(f"  Örnek sayısı  : {stats['samples']:,} piksel")
    print(f"  H persentil   : {stats['h_range']}  (ort: {stats['h_mean']:.1f}, σ={stats['h_std']:.1f})")
    print(f"  S persentil   : {stats['s_range']}  (ort: {stats['s_mean']:.1f}, σ={stats['s_std']:.1f})")
    print(f"  V persentil   : {stats['v_range']}  (ort: {stats['v_mean']:.1f}, σ={stats['v_std']:.1f})")
    print()
    print(f"  ÖNERİLEN HSV ALT  : {low}")
    print(f"  ÖNERİLEN HSV ÜST  : {high}")
    print()
    print(f"  config.py için:")
    print(f"      USE_MANUAL_HSV  = True")
    print(f"      MANUAL_HSV_LOW  = {low}")
    print(f"      MANUAL_HSV_HIGH = {high}")
    print("══════════════════════════════════════════════════════")
    print()


# ─── UI: çizim ────────────────────────────────────────────────────────────────
def draw_overlay(frame_bgr: np.ndarray, roi: ROIManager,
                 stats: dict | None, sample_count: int) -> np.ndarray:
    """Çerçeveye ROI'leri ve durum panelini bindirir."""
    out = frame_bgr.copy()

    # Onaylı ROI'ler (yeşil)
    for i, (x1, y1, x2, y2) in enumerate(roi.rects, 1):
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 220, 0), 2)
        cv2.putText(out, f"#{i}", (x1 + 4, y1 + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 0), 2)

    # Çizilmekte olan ROI (sarı)
    if roi.drawing and roi.start_pt and roi.cur_pt:
        cv2.rectangle(out, roi.start_pt, roi.cur_pt, (0, 220, 220), 2)

    # Üst panel
    panel_h = 110
    panel = np.zeros((panel_h, out.shape[1], 3), dtype=np.uint8)
    cv2.putText(panel, "MANUEL HSV KALIBRASYONU — Beyaz seridin uzerine 4-5 kutu ciz",
                (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 220), 1)
    cv2.putText(panel,
                f"ROI: {len(roi.rects)}  |  Toplam piksel: {sample_count:,}",
                (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    cv2.putText(panel,
                "[SPACE] onayla cizim   [Z] geri al   [R] sifirla   "
                "[C] hesapla   [S] kaydet   [Q] cik",
                (10, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)
    if stats is not None:
        cv2.putText(panel,
                    f"V%5={stats['v_range'][0]}  V%95={stats['v_range'][1]}  "
                    f"S%5={stats['s_range'][0]}  S%95={stats['s_range'][1]}",
                    (10, 96), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (100, 255, 100), 1)
    return np.vstack([panel, out])


# ─── Maske önizleme penceresi ─────────────────────────────────────────────────
def preview_mask(hsv_frame: np.ndarray, low, high) -> np.ndarray:
    """Hesaplanan HSV sınırlarıyla maskenin nasıl görüneceğini göster."""
    low_arr  = np.array(low,  dtype=np.uint8)
    high_arr = np.array(high, dtype=np.uint8)
    mask = cv2.inRange(hsv_frame, low_arr, high_arr)
    return mask


# ─── Ana program ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Manuel ROI tabanlı HSV kalibrasyonu (yarış öncesi)")
    parser.add_argument('--no-save-prompt', action='store_true',
                        help="S tuşuna basınca onay sormadan kaydet")
    args = parser.parse_args()

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║   MANUEL ROI-TABANLI HSV KALİBRASYONU                    ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    print("Kullanım:")
    print("  1. Fareyle BEYAZ ŞERİDİN üzerine dikdörtgenler çiz")
    print("  2. Farklı ışık/gölgeli yerlerden 4-5 örnek al")
    print("  3. C → istatistikleri gör")
    print("  4. S → config.py'ye kaydet")
    print()

    cam = Camera()
    roi = ROIManager()

    cv2.namedWindow("Kalibrasyon", cv2.WINDOW_NORMAL)
    cv2.setMouseCallback("Kalibrasyon", roi.on_mouse)

    cv2.namedWindow("Maske Onizleme", cv2.WINDOW_NORMAL)

    last_stats = None
    last_low   = None
    last_high  = None

    try:
        while True:
            frame_rgb = cam.capture()
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)

            # Mevcut ROI'lerden örnek topla
            samples = roi.collect_pixels(hsv)

            display = draw_overlay(frame_bgr, roi, last_stats,
                                    sample_count=samples.shape[0])
            cv2.imshow("Kalibrasyon", display)

            # Maske önizleme — son hesaplanan HSV ile
            if last_low is not None and last_high is not None:
                mask = preview_mask(hsv, last_low, last_high)
                cv2.imshow("Maske Onizleme", mask)
            else:
                cv2.imshow("Maske Onizleme",
                           np.zeros((HEIGHT, WIDTH), dtype=np.uint8))

            key = cv2.waitKey(20) & 0xFF
            if key == 0xFF:
                continue

            if key in (ord('q'), 27):  # Q veya Esc
                break
            elif key == ord('z'):
                roi.undo()
            elif key == ord('r'):
                roi.clear()
                last_stats = None
                last_low = last_high = None
            elif key == ord(' '):  # SPACE — sadece bilgilendirme; çizim mouse-up ile zaten ekleniyor
                print(f"[kalibrasyon] {len(roi.rects)} ROI onaylı, "
                      f"{samples.shape[0]:,} piksel toplandı")
            elif key == ord('c'):
                result = compute_hsv_bounds(samples)
                if result is None:
                    print(f"[kalibrasyon] Yetersiz örnek "
                          f"({samples.shape[0]} < {MIN_SAMPLES}). "
                          f"Daha fazla ROI ekle.")
                else:
                    last_low, last_high, last_stats = result
                    print_stats(last_low, last_high, last_stats)
            elif key == ord('s'):
                result = compute_hsv_bounds(samples)
                if result is None:
                    print(f"[kalibrasyon] Yetersiz örnek — kaydedilmedi.")
                    continue
                last_low, last_high, last_stats = result
                print_stats(last_low, last_high, last_stats)

                if not args.no_save_prompt:
                    print("config.py'ye yazılsın mı? [E/h] ", end='', flush=True)
                    try:
                        ans = input().strip().lower()
                    except EOFError:
                        ans = 'e'
                    if ans not in ('', 'e', 'y'):
                        print("[kalibrasyon] İptal edildi.")
                        continue

                ok = (write_cfg('USE_MANUAL_HSV',  True)
                      and write_cfg('MANUAL_HSV_LOW',  tuple(last_low))
                      and write_cfg('MANUAL_HSV_HIGH', tuple(last_high)))
                if ok:
                    print(f"[kalibrasyon] ✓ config.py güncellendi.")
                    print(f"   USE_MANUAL_HSV  = True")
                    print(f"   MANUAL_HSV_LOW  = {tuple(last_low)}")
                    print(f"   MANUAL_HSV_HIGH = {tuple(last_high)}")
                else:
                    print(f"[kalibrasyon] ✗ Kaydetme başarısız")
    finally:
        cam.close()
        cv2.destroyAllWindows()
        print("[kalibrasyon] Çıkıldı.")


if __name__ == "__main__":
    main()