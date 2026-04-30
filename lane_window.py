#!/usr/bin/env python3
"""
lane_window.py — 3 BOLGELI ORTA KARE TAKIBI

MANTIK:
  Goruntu 3 dikey bolgeye ayrilir:
    [SOL %20] [ORTA %60] [SAG %20]

  Iki beyaz seridin merkez noktasi (lane_center) hangi bolgede?
  - ORTA bolgede  -> error = 0 (DUZ GIT, salinim yok)
  - SAG bolgede   -> error pozitif  (sola don)
  - SOL bolgede   -> error negatif  (saga don)

  Tek serit gorunurse digerini onceki konumdan tahmin eder.

  Avantaj: Orta bolgede tolerans var, kucuk sapmalarda yalpalamiyor.
"""
import cv2
import numpy as np

from config import (
    WIDTH, HEIGHT, ROI_TOP_RATIO, PERSP_SRC,
    USE_MANUAL_HSV, MANUAL_HSV_LOW, MANUAL_HSV_HIGH,
    WHITE_HSV_LOW, WHITE_HSV_HIGH,
    LANE_WINDOW_CENTER_RATIO, LANE_WINDOW_SIDE_RATIO,
)
try:
    from config import LANE_WINDOW_USE_PERSPECTIVE
except ImportError:
    LANE_WINDOW_USE_PERSPECTIVE = True

# HSV - manuel kalibre edilmisse onu kullan, yoksa config WHITE_HSV
if USE_MANUAL_HSV:
    WHITE_LOW  = np.array(MANUAL_HSV_LOW,  dtype=np.uint8)
    WHITE_HIGH = np.array(MANUAL_HSV_HIGH, dtype=np.uint8)
else:
    WHITE_LOW  = np.array(WHITE_HSV_LOW,  dtype=np.uint8)
    WHITE_HIGH = np.array(WHITE_HSV_HIGH, dtype=np.uint8)

# Histogram tepe parametreleri
# DUSUK eski deger 50 — frame kenarindaki gurultu pixel'lere bile takilirdi
# Yuksek esik = sadece gercek serit cizgileri gecer
PEAK_MIN_HEIGHT = 2000   # bird-eye'da gercek serit ≈ 30+ kolon * 100 px sum = ~3000+
LANE_MIN_WIDTH  = 80     # iki tepe arasi minimum mesafe
LANE_MAX_WIDTH  = 500

# Frame kenar koruma: histogram'in ilk/son %X'i "lane" olamaz
# (bird-eye perspektifinde kenarlar genelde gurultu/border)
EDGE_IGNORE_RATIO = 0.05  # %5 = 40px her iki kenar

# Mask cok bos: hafizayi kullanma (stale veriyi engelle)
MIN_MASK_COVERAGE_PCT = 0.5  # %0.5 altinda mask = lane yok say


class LaneWindowDetector:
    """3 bolgeli ortalama dedektor — orta bolge olu bolge olarak calisir."""

    def __init__(self,
                 invert_steering: bool = False,
                 center_ratio: float | None = None,
                 side_ratio: float | None = None):
        self.invert       = invert_steering
        self.center_ratio = center_ratio if center_ratio is not None else LANE_WINDOW_CENTER_RATIO
        self.side_ratio   = side_ratio   if side_ratio   is not None else LANE_WINDOW_SIDE_RATIO

        # PERSPEKTIF kus bakisi: lane.py ile ayni transform
        self.use_perspective = LANE_WINDOW_USE_PERSPECTIVE
        if self.use_perspective:
            self.bird_w = WIDTH
            self.bird_h = int(HEIGHT * (1.0 - ROI_TOP_RATIO))
            src = np.float32(PERSP_SRC)
            dst = np.float32([
                [0,           0],
                [self.bird_w, 0],
                [0,           self.bird_h],
                [self.bird_w, self.bird_h],
            ])
            self.M = cv2.getPerspectiveTransform(src, dst)
        else:
            # Ham kamera: alt yariyi kullan (yakin yola odaklan)
            self.bird_w = WIDTH
            self.bird_h = int(HEIGHT * (1.0 - ROI_TOP_RATIO))
            self.M = None
            self._roi_top_y = HEIGHT - self.bird_h
        self.mid_x = self.bird_w // 2

        # 3 bolgenin sinirlari (kus bakisi genisliginde)
        side_px           = int(self.bird_w * self.side_ratio)
        self.left_zone_x  = side_px                       # 0..left_zone_x       = SOL
        self.right_zone_x = self.bird_w - side_px         # right_zone_x..bird_w = SAG
                                                          # arasi                = ORTA

        # Hafiza (serit kayboldugunda)
        self.prev_left:  int | None = None
        self.prev_right: int | None = None

        # EMA error smoothing (yalpa onleme)
        self._ema_error: float | None = None
        self._ema_alpha = 0.55  # 0=tam yumusak, 1=ham

        # Son frame tani bilgileri (DiagLogger icin)
        self.last_lane_center: int | None = None
        self.last_near_left:   int | None = None
        self.last_near_right:  int | None = None
        self.last_far_left:    int | None = None
        self.last_far_right:   int | None = None
        self.last_mask_pct:    float = 0.0
        self.last_v_mean:      float = 0.0

    def process(self, frame_rgb: np.ndarray) -> tuple:
        """
        Returns:
            error: int  (0 = ortada, +sola, -saga)
            debug: BGR debug (kus bakisi)
        """
        # PERSPEKTIF kus bakisi donusumu (yamuk -> kare) veya basit kirpma
        if self.use_perspective:
            bird = cv2.warpPerspective(frame_rgb, self.M, (self.bird_w, self.bird_h),
                                       flags=cv2.INTER_LINEAR)
        else:
            bird = frame_rgb[self._roi_top_y:, :]

        # HSV maskesi (config degerleriyle)
        hsv  = cv2.cvtColor(bird, cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, WHITE_LOW, WHITE_HIGH)

        # Morfoloji ile gurultu temizleme
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        # Tani: maske yogunlugu + V ortalamasi
        total_px = mask.size
        white_px = int(np.count_nonzero(mask))
        self.last_mask_pct = 100.0 * white_px / max(total_px, 1)
        self.last_v_mean   = float(np.mean(hsv[:, :, 2]))

        # FIX: Mask cok bos -> stale memory kullanma
        mask_too_empty = self.last_mask_pct < MIN_MASK_COVERAGE_PCT

        # ===========================================================
        # IKI-KATLI HISTOGRAM: yakin (alt %60) + uzak (ust %40)
        # Yakin = stabil yon | Uzak = viraj ongorusu (lookahead)
        # ===========================================================
        h_split = int(self.bird_h * 0.4)  # ust %40 = uzak
        far_hist  = np.sum(mask[:h_split, :], axis=0)
        near_hist = np.sum(mask[h_split:, :], axis=0)

        # Yakin tepe arama (ana referans)
        left_x, right_x = self._find_two_peaks(near_hist)

        # Uzak tepe arama (lookahead — viraj erken tespiti)
        far_left_x, far_right_x = self._find_two_peaks(far_hist)

        # Hafiza fallback (mask yeterince doluyken)
        if mask_too_empty:
            # Mask cok bos: stale verileri sil, hicbir sey kullanma
            self.prev_left  = None
            self.prev_right = None
            left_x  = None
            right_x = None
        else:
            if left_x  is not None: self.prev_left  = left_x
            else:                   left_x  = self.prev_left
            if right_x is not None: self.prev_right = right_x
            else:                   right_x = self.prev_right

        # lane_center hesapla
        if left_x is not None and right_x is not None:
            lane_center = (left_x + right_x) // 2
        elif left_x is not None:
            # Sag yok -> tahmini 200 px sagda
            lane_center = left_x + 150
        elif right_x is not None:
            # Sol yok -> tahmini 200 px solda
            lane_center = right_x - 150
        else:
            lane_center = None

        # ===========================================================
        # UZAK lane center (lookahead — viraj ongorusu)
        # ===========================================================
        if far_left_x is not None and far_right_x is not None:
            far_lane_center = (far_left_x + far_right_x) // 2
        elif far_left_x is not None:
            far_lane_center = far_left_x + 150
        elif far_right_x is not None:
            far_lane_center = far_right_x - 150
        else:
            far_lane_center = None

        # ===========================================================
        # HATA HESABI - lane.py ile AYNI konvansiyon:
        #   error = mid_x - lane_center
        #   error > 0 -> lane SOLDA -> sola don (controller +correction)
        #   error < 0 -> lane SAGDA -> saga don
        # ===========================================================
        if lane_center is None:
            error = None
            zone  = "YOK"
            self._ema_error = None  # reset
        else:
            # YAKIN error (ana sinyal — %70 agirlik)
            near_err = self.mid_x - lane_center
            # UZAK error (lookahead — %30 agirlik, viraj erken tepkisi)
            if far_lane_center is not None:
                far_err = self.mid_x - far_lane_center
                raw_error = 0.7 * near_err + 0.3 * far_err
            else:
                raw_error = float(near_err)

            # EMA smoothing (yalpa filtreleme)
            if self._ema_error is None:
                self._ema_error = raw_error
            else:
                self._ema_error = (self._ema_alpha * raw_error
                                   + (1.0 - self._ema_alpha) * self._ema_error)

            # Bolge bilgisi (sadece gorsel)
            if self.left_zone_x <= lane_center <= self.right_zone_x:
                zone = "ORTA"
            elif lane_center < self.left_zone_x:
                zone = "SOL"
            else:
                zone = "SAG"

            # Kucuk olu bolge
            if abs(self._ema_error) < 8:
                error = 0
            else:
                error = int(self._ema_error)

        if error is not None and self.invert:
            error = -error

        # DiagLogger icin tani bilgileri kaydet
        self.last_lane_center = lane_center
        self.last_near_left   = left_x
        self.last_near_right  = right_x
        self.last_far_left    = far_left_x
        self.last_far_right   = far_right_x

        debug = self._draw_debug(bird, mask, left_x, right_x, lane_center, error, zone)
        return error, debug

    def _find_two_peaks(self, hist):
        """Histogramdan iki beyaz serit tepe noktasi.

        FIX: Frame kenarlarindaki gurultu/border pixel'leri reddet.
        FIX: PEAK_MIN_HEIGHT yuksek — sadece GERCEK serit cizgileri gecer.
        """
        n = len(hist)
        mid = n // 2
        edge = int(n * EDGE_IGNORE_RATIO)  # her iki kenardan ignore edilecek px

        # Sol yari: edge..mid arasinda ara (en sol kenar = noise/border)
        left_h  = hist[edge:mid].copy() if mid > edge else np.zeros(0)
        # Sag yari: mid..(n-edge) arasinda ara (en sag kenar = noise/border)
        right_h = hist[mid:n-edge].copy() if (n - edge) > mid else np.zeros(0)

        left_x  = (int(np.argmax(left_h))  + edge) if left_h.size  and left_h.max()  > PEAK_MIN_HEIGHT else None
        right_x = (int(np.argmax(right_h)) + mid)  if right_h.size and right_h.max() > PEAK_MIN_HEIGHT else None

        # Cok yakin tepeler tek serittir -> zayif olani at
        if left_x is not None and right_x is not None:
            if right_x - left_x < LANE_MIN_WIDTH:
                if hist[left_x] >= hist[right_x]: right_x = None
                else:                              left_x  = None

        return left_x, right_x

    def _draw_debug(self, bird_rgb, mask, lx, rx, cx, err, zone):
        # NOT: RGB donduruyoruz - main.py kendisi BGR'a cevirecek (lane.py ile ayni convention)
        # HSV maskesini bird uzerine overlay et (yansimalari gorelim)
        mask_rgb = cv2.cvtColor(mask, cv2.COLOR_GRAY2RGB)
        debug    = cv2.addWeighted(bird_rgb, 0.6, mask_rgb, 0.4, 0)
        h, w     = debug.shape[:2]

        # 3 bolge — yari saydam overlay (RGB sirasinda: kirmizi=(255,0,0), yesil=(0,255,0))
        overlay = debug.copy()
        cv2.rectangle(overlay, (0, 0), (self.left_zone_x, h),
                      (80, 0, 0), -1)        # SOL kirmizi (RGB)
        cv2.rectangle(overlay, (self.right_zone_x, 0), (w, h),
                      (80, 0, 0), -1)        # SAG kirmizi
        cv2.rectangle(overlay, (self.left_zone_x, 0), (self.right_zone_x, h),
                      (0, 80, 0), -1)        # ORTA yesil
        cv2.addWeighted(overlay, 0.18, debug, 0.82, 0, debug)

        # Bolge sinir cizgileri
        cv2.line(debug, (self.left_zone_x, 0),  (self.left_zone_x, h),  (0, 255, 255), 1)
        cv2.line(debug, (self.right_zone_x, 0), (self.right_zone_x, h), (0, 255, 255), 1)

        # Maske mini-preview
        mask_color   = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        mask_resized = cv2.resize(mask_color, (w // 4, h // 4))
        debug[h - h//4:, w - w//4:] = mask_resized

        # Beyaz serit cizgileri
        if lx is not None:
            cv2.line(debug, (lx, 0), (lx, h), (0, 255, 0), 3)
        if rx is not None:
            cv2.line(debug, (rx, 0), (rx, h), (0, 255, 0), 3)

        # Lane center (sari daire)
        if cx is not None:
            color = (0, 255, 255) if zone == "ORTA" else (0, 100, 255)
            cv2.circle(debug, (cx, h - 60), 12, color, -1)
            cv2.line(debug, (cx, 0), (cx, h), color, 2)

        # Goruntu merkezi (gri)
        cv2.line(debug, (self.mid_x, 0), (self.mid_x, h), (128, 128, 128), 1)

        # Bilgi metni
        err_str = f"ERR:{err:+4d}" if err is not None else "ERR:NONE"
        cv2.putText(debug, f"[{zone}] {err_str}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    (0, 255, 0) if zone == "ORTA" else (0, 165, 255), 2)
        cv2.putText(debug,
                    f"side={int(self.side_ratio*100)}% | center={int(self.center_ratio*100)}%",
                    (10, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        persp_str = "PERSP:ON" if self.use_perspective else "PERSP:OFF"
        hsv_str   = "HSV:MANUAL" if USE_MANUAL_HSV else "HSV:AUTO"
        cv2.putText(debug, f"{persp_str} | {hsv_str}",
                    (10, 75),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
        cv2.putText(debug,
                    f"H:{WHITE_LOW[0]}-{WHITE_HIGH[0]} S:{WHITE_LOW[1]}-{WHITE_HIGH[1]} V:{WHITE_LOW[2]}-{WHITE_HIGH[2]}",
                    (10, 95),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1)

        return debug


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("LaneWindowDetector test — 3 bolgeli olu bolge takip")
    print("Q: cik | I: invert | +/-: side ratio degis")
    try:
        from picamera2 import Picamera2
        cam = Picamera2()
        cam.configure(cam.create_preview_configuration(
            main={"size": (WIDTH, HEIGHT), "format": "RGB888"}
        ))
        cam.start()
        _pi = True
    except Exception:
        cam = cv2.VideoCapture(0)
        cam.set(cv2.CAP_PROP_FRAME_WIDTH,  WIDTH)
        cam.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        _pi = False

    det = LaneWindowDetector()
    while True:
        if _pi:
            f = cam.capture_array()
            if f.ndim == 3 and f.shape[2] == 4: f = f[:, :, :3]
        else:
            ok, f = cam.read()
            if not ok: break
            f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
        e, d = det.process(f)
        cv2.imshow("Lane Window (3 bolge)", cv2.cvtColor(d, cv2.COLOR_RGB2BGR))
        k = cv2.waitKey(1) & 0xFF
        if k == ord('q'): break
        if k == ord('i'): det.invert = not det.invert; print("invert:", det.invert)
        if k == ord('+') or k == ord('='):
            det.side_ratio = min(0.45, det.side_ratio + 0.05)
            det.left_zone_x  = int(det.bird_w * det.side_ratio)
            det.right_zone_x = det.bird_w - det.left_zone_x
            print("side_ratio:", det.side_ratio)
        if k == ord('-'):
            det.side_ratio = max(0.05, det.side_ratio - 0.05)
            det.left_zone_x  = int(det.bird_w * det.side_ratio)
            det.right_zone_x = det.bird_w - det.left_zone_x
            print("side_ratio:", det.side_ratio)

    if _pi: cam.stop()
    else:   cam.release()
    cv2.destroyAllWindows()

