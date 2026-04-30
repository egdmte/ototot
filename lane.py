
# =============================================================================
# lane.py  —  Gelişmiş kuş bakışı şerit dedektörü
#
# ÖZELLİKLER:
#   ✓ Adaptif + Otomatik HSV kalibrasyonu (warmup ile)
#   ✓ HSV ∪ Sobel kenar maskesi birleşimi (yansıma direnci)
#   ✓ 3 ROI bölgesel histogram (yakın/orta/uzak)
#   ✓ Confidence-weighted ROI oylaması (sinyali zayıf ROI azalır)
#   ✓ Şerit genişliği sanity check (yansıma reddi)
#   ✓ 2. derece polinom fit (eğri tahmini)
#   ✓ Lookahead steering (pure-pursuit-lite)
#   ✓ EMA smoothing + dead-zone (yalpa önleme)
#   ✓ Şerit hafızası (kayıp karelere dayanım)
# =============================================================================
import cv2
import numpy as np

from config import (
    WIDTH, HEIGHT, ROI_TOP_RATIO, PERSP_SRC,
    MIN_LANE_SIGNAL, ASSUMED_LANE_WIDTH,
    WHITE_HSV_LOW, WHITE_HSV_HIGH,
    WHITE_HSV_LOW_DARK, WHITE_HSV_HIGH_DARK,
    WHITE_HSV_LOW_NORMAL, WHITE_HSV_HIGH_NORMAL,
    WHITE_HSV_LOW_BRIGHT, WHITE_HSV_HIGH_BRIGHT,
    LANE_MEMORY_FRAMES, LANE_SEARCH_WINDOW,
    CLAHE_CLIP_LIMIT, CLAHE_TILE_SIZE, LANE_CONTINUITY_RATIO,
    LANE_FAR_RATIO, LANE_MID_RATIO, LANE_NEAR_RATIO,
    LANE_FAR_WEIGHT, LANE_MID_WEIGHT, LANE_NEAR_WEIGHT,
    ERROR_EMA_ALPHA, ERROR_DEAD_ZONE, LANE_FAR_MAX_DEVIATION,
    # YENİ
    LANE_WIDTH_TOLERANCE_RATIO, LANE_WIDTH_MIN_RATIO,
    CONFIDENCE_WEIGHTING, CONFIDENCE_MIN_PEAK,
    USE_EDGE_DETECTOR, SOBEL_KERNEL_SIZE, SOBEL_THRESHOLD, EDGE_FUSION_WEIGHT,
    AUTO_HSV_CALIBRATION, AUTO_HSV_CALIB_FRAMES, AUTO_HSV_CALIB_PERCENTILE,
    AUTO_HSV_CALIB_MARGIN_S, AUTO_HSV_CALIB_MARGIN_V,
    USE_POLYNOMIAL_FIT, POLY_FIT_MIN_POINTS, POLY_FIT_BAND_HEIGHT, POLY_FIT_OUTLIER_STD,
    LOOKAHEAD_BASE_PX, LOOKAHEAD_SPEED_FACTOR, LOOKAHEAD_BLEND_RATIO,
    USE_MANUAL_HSV, MANUAL_HSV_LOW, MANUAL_HSV_HIGH,
)


class LaneDetector:
    """Kuş bakışında şerit tespiti — tüm iyileştirmelerle.

    hata > 0  →  şerit merkezi kare merkezinin SOLunda  →  sola dön
    hata < 0  →  şerit merkezi kare merkezinin SAĞında  →  sağa dön
    """

    def __init__(self):
        self.bird_w = WIDTH
        self.bird_h = int(HEIGHT * (1.0 - ROI_TOP_RATIO))
        self.mid    = self.bird_w // 2

        src = np.float32(PERSP_SRC)
        dst = np.float32([
            [0,           0],
            [self.bird_w, 0],
            [0,           self.bird_h],
            [self.bird_w, self.bird_h],
        ])
        self.M    = cv2.getPerspectiveTransform(src, dst)
        self.Minv = cv2.getPerspectiveTransform(dst, src)

        # Şerit konumu hafızası: (son_sütun, son_görüldükten_bu_yana_kare)
        self._left_mem:  tuple | None = None
        self._right_mem: tuple | None = None

        # EMA (yumuşatılmış hata) — yalpa önleme
        self._ema_error: float | None = None

        # Morfoloji kernel'i (3×3 — ince bant çizgilerini korur)
        self._kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))

        # CLAHE: spot ışık / zemin yansımalarını normalize eder
        self._clahe = cv2.createCLAHE(
            clipLimit=CLAHE_CLIP_LIMIT,
            tileGridSize=(CLAHE_TILE_SIZE, CLAHE_TILE_SIZE),
        )

        # ===== OTOMATİK HSV KALİBRASYONU =====
        # Manuel kalibrasyon aktifse otomatik warmup'a gerek yok.
        self._calib_done   = USE_MANUAL_HSV or (not AUTO_HSV_CALIBRATION)
        self._calib_frames = 0
        self._calib_v_samples: list = []  # V kanalından beyaz aday değerleri
        self._calib_s_samples: list = []  # S kanalı
        # Çalışma zamanı HSV (kalibrasyon sonrası override edilir)
        self._auto_white_low:  np.ndarray | None = None
        self._auto_white_high: np.ndarray | None = None

        # ===== POLİNOM FIT durum =====
        # Son fit edilen polinom katsayıları (x = a*y² + b*y + c)
        self._poly_left:  np.ndarray | None = None
        self._poly_right: np.ndarray | None = None

        # Hız bilgisi (lookahead için dışarıdan set edilir)
        self.current_speed: float = 0.0

        # Son hesaplanan ham metrikler (debug + dış kullanım için)
        self.last_lane_width: float = ASSUMED_LANE_WIDTH
        self.last_confidence: dict = {'near': 0.0, 'mid': 0.0, 'far': 0.0}
        self.last_status: str = "init"

    # ==================================================================
    # ANA İŞLEM
    # ==================================================================
    def process(self, frame: np.ndarray) -> tuple:
        """RGB kareyi işler.

        Döndürür
        --------
        error : int | None
        debug : np.ndarray  — açıklamalı kuş bakışı görüntüsü (RGB)
        """
        # 1. Kuş bakışı perspektif dönüşümü
        bird = cv2.warpPerspective(frame, self.M, (self.bird_w, self.bird_h))

        # 2. CLAHE: L kanalında yerel kontrast eşitleme
        lab = cv2.cvtColor(bird, cv2.COLOR_RGB2LAB)
        l_ch, a_ch, b_ch = cv2.split(lab)
        l_eq = self._clahe.apply(l_ch)
        bird_proc = cv2.cvtColor(cv2.merge([l_eq, a_ch, b_ch]), cv2.COLOR_LAB2RGB)

        # 3. HSV maskesi (otomatik veya adaptif)
        hsv  = cv2.cvtColor(bird_proc, cv2.COLOR_RGB2HSV)
        v_mean = float(np.mean(hsv[:, :, 2]))

        # ----- Otomatik kalibrasyon warmup -----
        if not self._calib_done:
            self._collect_calibration_samples(hsv)
            if self._calib_frames >= AUTO_HSV_CALIB_FRAMES:
                self._finalize_auto_calibration()

        white_low, white_high = self._select_hsv_range(v_mean)
        hsv_mask = cv2.inRange(hsv, white_low, white_high)

        # 4. Sobel kenar maskesi (HSV'ye paralel ikinci detektör)
        if USE_EDGE_DETECTOR:
            edge_mask = self._compute_edge_mask(l_eq)
            # Birleşik maske: HSV önemli ama kenar destekçi (OR mantığı + ağırlık)
            mask = cv2.addWeighted(hsv_mask, 1.0 - EDGE_FUSION_WEIGHT,
                                   edge_mask, EDGE_FUSION_WEIGHT, 0)
            mask = cv2.threshold(mask, 64, 255, cv2.THRESH_BINARY)[1]
        else:
            mask = hsv_mask

        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  self._kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._kernel)

        # 5. Sütun sürekliliği ağırlığı (yansıma filtresi)
        col_cov = (mask > 0).sum(axis=0).astype(np.float32)
        min_cov = max(float(self.bird_h) * LANE_CONTINUITY_RATIO, 1.0)
        continuity_w = np.minimum(col_cov / min_cov, 1.0)

        # 6. Üç ROI dilim histogramları
        near_rows  = int(self.bird_h * LANE_NEAR_RATIO)
        mid_rows   = int(self.bird_h * LANE_MID_RATIO)
        far_rows   = int(self.bird_h * LANE_FAR_RATIO)
        near_start = self.bird_h - near_rows
        mid_start  = far_rows
        mid_end    = far_rows + mid_rows

        def _slice_hist(m):
            h = np.sum(m, axis=0).astype(np.float32) * continuity_w
            return cv2.GaussianBlur(h.reshape(1, -1), (1, 31), 0).flatten()

        near_hist = _slice_hist(mask[near_start:])
        mid_hist  = _slice_hist(mask[mid_start:mid_end])
        far_hist  = _slice_hist(mask[:far_rows])

        # 7. Tepe bulma — yakın hafızalı, orta/uzak serbest
        near_lp, near_ls, near_lh = self._find_peak(
            near_hist, 0, self.mid,
            self._left_mem[0] if self._left_mem else None)
        near_rp, near_rs, near_rh = self._find_peak(
            near_hist, self.mid, self.bird_w,
            self._right_mem[0] if self._right_mem else None)
        mid_lp, mid_ls, mid_lh = self._find_peak(mid_hist, 0,        self.mid,    None)
        mid_rp, mid_rs, mid_rh = self._find_peak(mid_hist, self.mid, self.bird_w, None)
        far_lp, far_ls, far_lh = self._find_peak(far_hist, 0,        self.mid,    None)
        far_rp, far_rs, far_rh = self._find_peak(far_hist, self.mid, self.bird_w, None)

        # 8. Yakın bölge hafıza güncelleme
        left_valid  = self._update_memory('left',  near_lp, near_ls)
        right_valid = self._update_memory('right', near_rp, near_rs)
        if left_valid:  near_lp = self._left_mem[0]
        if right_valid: near_rp = self._right_mem[0]

        # 9. ŞERİT GENİŞLİĞİ SANITY CHECK (her ROI için)
        # Sol-sağ peak mesafesi mantıksızsa bir taraf yansımaya kaymıştır.
        near_lp, near_rp, near_ls, near_rs, near_w = self._validate_lane_pair(
            near_lp, near_rp, near_ls or left_valid, near_rs or right_valid)
        mid_lp,  mid_rp,  mid_ls,  mid_rs,  _ = self._validate_lane_pair(
            mid_lp, mid_rp, mid_ls, mid_rs)
        far_lp,  far_rp,  far_ls,  far_rs,  _ = self._validate_lane_pair(
            far_lp, far_rp, far_ls, far_rs)

        if near_w > 0:
            self.last_lane_width = 0.85 * self.last_lane_width + 0.15 * near_w

        # 10. Bölge merkezleri
        def _center(lp, lv, rp, rv):
            if lv and rv:  return (lp + rp) // 2
            elif lv:       return lp + int(self.last_lane_width) // 2
            elif rv:       return rp - int(self.last_lane_width) // 2
            return None

        # validate_lane_pair'ın döndürdüğü ls/rs zaten memory'yi içeriyor.
        near_c = _center(near_lp, near_ls, near_rp, near_rs)
        mid_c  = _center(mid_lp,  mid_ls,  mid_rp,  mid_rs)
        far_c  = _center(far_lp,  far_ls,  far_rp,  far_rs)

        # YANSIMA filtresi: hafızasız bölge yakından çok saparsa reddet
        if near_c is not None:
            if mid_c is not None and abs(mid_c - near_c) > LANE_FAR_MAX_DEVIATION:
                mid_c = None
            if far_c is not None and abs(far_c - near_c) > LANE_FAR_MAX_DEVIATION * 1.5:
                far_c = None

        # 11. CONFIDENCE-WEIGHTED ROI VOTING
        # Histogram tepe yüksekliği = ROI'nun güvenilirliği
        near_conf = self._roi_confidence(near_lh, near_rh, near_ls, near_rs)
        mid_conf  = self._roi_confidence(mid_lh,  mid_rh,  mid_ls,  mid_rs)
        far_conf  = self._roi_confidence(far_lh,  far_rh,  far_ls,  far_rs)
        self.last_confidence = {'near': near_conf, 'mid': mid_conf, 'far': far_conf}

        # 12. Histogram tabanlı ağırlıklı hata
        valid_centers = [c for c in [near_c, mid_c, far_c] if c is not None]
        if not valid_centers:
            self.last_status = "KAYIP"
            return None, self._blank_debug(bird, mask)

        if CONFIDENCE_WEIGHTING:
            # Confidence × statik ağırlık
            total_w = 0.0
            weighted = 0.0
            if near_c is not None:
                w = LANE_NEAR_WEIGHT * near_conf
                weighted += w * (self.mid - near_c); total_w += w
            if mid_c is not None:
                w = LANE_MID_WEIGHT * mid_conf
                weighted += w * (self.mid - mid_c); total_w += w
            if far_c is not None:
                w = LANE_FAR_WEIGHT * far_conf
                weighted += w * (self.mid - far_c); total_w += w
            histogram_error = weighted / total_w if total_w > 0 else 0.0
        else:
            total_w = 0.0
            weighted = 0.0
            for c, w in [(near_c, LANE_NEAR_WEIGHT),
                         (mid_c,  LANE_MID_WEIGHT),
                         (far_c,  LANE_FAR_WEIGHT)]:
                if c is not None:
                    weighted += w * (self.mid - c); total_w += w
            histogram_error = weighted / total_w if total_w > 0 else 0.0

        # 13. POLİNOM FIT + LOOKAHEAD STEERING
        lookahead_error = None
        poly_left, poly_right = None, None
        if USE_POLYNOMIAL_FIT:
            poly_left, poly_right = self._fit_polynomials(mask)
            self._poly_left, self._poly_right = poly_left, poly_right
            lookahead_error = self._compute_lookahead_error(poly_left, poly_right)

        # 14. Birleşik hata: histogram + lookahead karışımı
        if lookahead_error is not None:
            # Polinom fit varsa, lookahead'i karıştır
            blend = LOOKAHEAD_BLEND_RATIO
            raw_error = (1.0 - blend) * histogram_error + blend * lookahead_error
        else:
            raw_error = histogram_error

        # 15. EMA smoothing
        if self._ema_error is None:
            self._ema_error = raw_error
        else:
            self._ema_error = (ERROR_EMA_ALPHA * raw_error
                               + (1.0 - ERROR_EMA_ALPHA) * self._ema_error)

        # 16. ÖLÜ BÖLGE
        if abs(self._ema_error) < ERROR_DEAD_ZONE:
            error = 0
        else:
            error = int(self._ema_error)

        lane_center = int(np.clip(self.mid - error, 0, self.bird_w - 1))
        self.last_status = ("Sol+Sağ" if near_ls and near_rs
                            else "Yalnız Sol" if near_ls
                            else "Yalnız Sağ" if near_rs
                            else "Tahmin")

        # 17. Debug görüntüsü
        debug = self._draw_debug(
            bird_proc, mask,
            near_lp, near_rp, near_ls, near_rs,
            mid_lp if mid_ls else None, mid_rp if mid_rs else None,
            far_lp if far_ls else None, far_rp if far_rs else None,
            lane_center, error, v_mean,
            poly_left, poly_right, lookahead_error,
        )
        return error, debug

    # ==================================================================
    # OTOMATİK HSV KALİBRASYONU
    # ==================================================================
    def _collect_calibration_samples(self, hsv: np.ndarray) -> None:
        """Warmup süresince beyaz aday piksellerin V/S değerlerini topla."""
        v = hsv[:, :, 2].flatten()
        s = hsv[:, :, 1].flatten()
        # En parlak %8 (üst persentil) = beyaz adayı
        cutoff = np.percentile(v, AUTO_HSV_CALIB_PERCENTILE)
        mask_idx = v >= cutoff
        if mask_idx.any():
            self._calib_v_samples.append(v[mask_idx])
            self._calib_s_samples.append(s[mask_idx])
        self._calib_frames += 1

    def _finalize_auto_calibration(self) -> None:
        """Topladığımız örneklerden otomatik HSV alt/üst sınırları üret."""
        if not self._calib_v_samples:
            self._calib_done = True
            print("[lane] Otomatik HSV kalibrasyonu: yetersiz örnek, varsayılan kullanılıyor")
            return
        v_all = np.concatenate(self._calib_v_samples)
        s_all = np.concatenate(self._calib_s_samples)
        # Beyaz şerit: yüksek V, düşük S
        v_low  = max(int(np.percentile(v_all, 20)) - AUTO_HSV_CALIB_MARGIN_V, 60)
        s_high = min(int(np.percentile(s_all, 90)) + AUTO_HSV_CALIB_MARGIN_S, 130)
        self._auto_white_low  = np.array([0,   0,      v_low], dtype=np.uint8)
        self._auto_white_high = np.array([180, s_high, 255],   dtype=np.uint8)
        self._calib_done = True
        # Bellek temizle
        self._calib_v_samples = []
        self._calib_s_samples = []
        print(f"[lane] Otomatik HSV kalibrasyonu tamamlandı: "
              f"V≥{v_low}, S≤{s_high}")

    def _select_hsv_range(self, v_mean: float) -> tuple:
        """HSV aralığını öncelik sırasına göre seç:
          1) MANUEL (hsv_calibrate_roi.py ile kalibre edilmişse)  — en güvenilir
          2) OTOMATİK (warmup'ta toplanmışsa)
          3) ADAPTİF (DARK/NORMAL/BRIGHT — klasik fallback)
        """
        # 1) MANUEL HSV — en yüksek öncelik
        if USE_MANUAL_HSV:
            return (np.array(MANUAL_HSV_LOW,  dtype=np.uint8),
                    np.array(MANUAL_HSV_HIGH, dtype=np.uint8))
        # 2) OTOMATİK HSV
        if self._auto_white_low is not None:
            return self._auto_white_low, self._auto_white_high
        # 3) ADAPTİF HSV (klasik)
        if v_mean < 100:
            return (np.array(WHITE_HSV_LOW_DARK,  dtype=np.uint8),
                    np.array(WHITE_HSV_HIGH_DARK, dtype=np.uint8))
        elif v_mean > 200:
            return (np.array(WHITE_HSV_LOW_BRIGHT,  dtype=np.uint8),
                    np.array(WHITE_HSV_HIGH_BRIGHT, dtype=np.uint8))
        else:
            return (np.array(WHITE_HSV_LOW_NORMAL,  dtype=np.uint8),
                    np.array(WHITE_HSV_HIGH_NORMAL, dtype=np.uint8))

    # ==================================================================
    # SOBEL KENAR MASKESİ
    # ==================================================================
    def _compute_edge_mask(self, l_channel: np.ndarray) -> np.ndarray:
        """Sobel X gradient → şerit kenarları. Aydınlatmadan bağımsız."""
        # Gauss bulanıklık (gürültü azalt)
        blur = cv2.GaussianBlur(l_channel, (5, 5), 0)
        # X yönlü gradient (dikey çizgileri yakalar)
        sx = cv2.Sobel(blur, cv2.CV_16S, 1, 0, ksize=SOBEL_KERNEL_SIZE)
        sx = cv2.convertScaleAbs(sx)
        _, edge = cv2.threshold(sx, SOBEL_THRESHOLD, 255, cv2.THRESH_BINARY)
        # Genişletme: tek pikselli kenarları sütun sürekliliği için biraz şişir
        edge = cv2.dilate(edge, self._kernel, iterations=1)
        return edge

    # ==================================================================
    # ŞERİT GENİŞLİĞİ DOĞRULAMA
    # ==================================================================
    def _validate_lane_pair(self, lp: int, rp: int,
                            ls: bool, rs: bool) -> tuple:
        """Sol-sağ tepe noktası ASSUMED_LANE_WIDTH ile uyumlu mu?
        Değilse hangi taraf 'şüpheli' (genelde dış mekan yansıması)
        — daha düşük signal'ı reddeder.

        Döndürür: (lp, rp, ls, rs, measured_width)
        """
        if not (ls and rs):
            return lp, rp, ls, rs, 0.0
        width = float(rp - lp)
        if width <= 0:
            return lp, rp, False, False, 0.0
        expected = float(self.last_lane_width)
        tol = LANE_WIDTH_TOLERANCE_RATIO * expected
        if abs(width - expected) <= tol and width >= LANE_WIDTH_MIN_RATIO * expected:
            return lp, rp, ls, rs, width
        # Şerit genişliği mantıksız → bir taraf yansıma. Tekiyle yetin.
        # Hangi taraf hafızaya daha yakın → onu tut, diğerini at.
        if self._left_mem and self._right_mem:
            ldev = abs(lp - self._left_mem[0])
            rdev = abs(rp - self._right_mem[0])
            if ldev < rdev:
                return lp, rp, ls, False, 0.0
            else:
                return lp, rp, False, rs, 0.0
        # Hafıza yok → daha merkeze yakın taraf daha güvenilir
        l_dist = abs(lp - self.mid)
        r_dist = abs(rp - self.mid)
        if l_dist < r_dist:
            return lp, rp, ls, False, 0.0
        else:
            return lp, rp, False, rs, 0.0

    # ==================================================================
    # CONFIDENCE
    # ==================================================================
    @staticmethod
    def _roi_confidence(lh: float, rh: float, lv: bool, rv: bool) -> float:
        """ROI güveni: tepe yüksekliklerinin minimum eşikle normalize edilmiş ortalaması."""
        if not (lv or rv):
            return 0.0
        peaks = []
        if lv: peaks.append(lh)
        if rv: peaks.append(rh)
        avg_peak = float(np.mean(peaks))
        # 0..1 arasında normalize
        return float(np.clip(avg_peak / (CONFIDENCE_MIN_PEAK * 3.0), 0.0, 1.0))

    # ==================================================================
    # POLİNOM FIT (2. derece)
    # ==================================================================
    def _fit_polynomials(self, mask: np.ndarray) -> tuple:
        """Sol ve sağ şerit için x = a*y² + b*y + c polinomları fit eder.

        Yöntem: Görüntüyü dikey bantlara böl, her bantta sol/sağ
        bölgenin ağırlık merkezini al, RANSAC benzeri outlier reddet.
        """
        h, w = mask.shape
        band_h = max(POLY_FIT_BAND_HEIGHT, 4)
        n_bands = h // band_h

        left_pts:  list = []
        right_pts: list = []

        # Önceki polinom varsa, onu rehber olarak kullan
        prev_left  = self._poly_left
        prev_right = self._poly_right

        for i in range(n_bands):
            y0 = i * band_h
            y1 = y0 + band_h
            yc = (y0 + y1) // 2
            band = mask[y0:y1]
            col_sum = band.sum(axis=0).astype(np.float32)

            # SOL yarı: rehber varsa yakınında ara, yoksa serbest
            if prev_left is not None:
                xl_guess = int(np.polyval(prev_left, yc))
                lo_l = max(0, xl_guess - LANE_SEARCH_WINDOW)
                hi_l = min(self.mid, xl_guess + LANE_SEARCH_WINDOW)
            else:
                lo_l, hi_l = 0, self.mid
            if hi_l > lo_l:
                seg_l = col_sum[lo_l:hi_l]
                if seg_l.sum() > MIN_LANE_SIGNAL * 0.3:
                    xl = lo_l + int(np.average(np.arange(hi_l - lo_l), weights=seg_l))
                    left_pts.append((yc, xl))

            # SAĞ yarı
            if prev_right is not None:
                xr_guess = int(np.polyval(prev_right, yc))
                lo_r = max(self.mid, xr_guess - LANE_SEARCH_WINDOW)
                hi_r = min(w, xr_guess + LANE_SEARCH_WINDOW)
            else:
                lo_r, hi_r = self.mid, w
            if hi_r > lo_r:
                seg_r = col_sum[lo_r:hi_r]
                if seg_r.sum() > MIN_LANE_SIGNAL * 0.3:
                    xr = lo_r + int(np.average(np.arange(hi_r - lo_r), weights=seg_r))
                    right_pts.append((yc, xr))

        poly_left  = self._fit_with_outlier_rejection(left_pts)
        poly_right = self._fit_with_outlier_rejection(right_pts)
        return poly_left, poly_right

    @staticmethod
    def _fit_with_outlier_rejection(pts: list) -> np.ndarray | None:
        """2. derece polinom fit + outlier reddi (1 iterasyon).
        Geri dönüş: np.poly katsayıları (en yüksek dereceden) veya None.
        """
        if len(pts) < POLY_FIT_MIN_POINTS:
            return None
        ys = np.array([p[0] for p in pts], dtype=np.float32)
        xs = np.array([p[1] for p in pts], dtype=np.float32)
        try:
            coeffs = np.polyfit(ys, xs, 2)
        except (np.linalg.LinAlgError, ValueError):
            return None
        # Outlier reddi
        residuals = xs - np.polyval(coeffs, ys)
        std = float(np.std(residuals))
        if std > 1e-3:
            keep = np.abs(residuals) <= POLY_FIT_OUTLIER_STD * std
            if keep.sum() >= POLY_FIT_MIN_POINTS:
                try:
                    coeffs = np.polyfit(ys[keep], xs[keep], 2)
                except (np.linalg.LinAlgError, ValueError):
                    pass
        return coeffs

    # ==================================================================
    # LOOKAHEAD STEERING
    # ==================================================================
    def _compute_lookahead_error(self, poly_l, poly_r) -> float | None:
        """Polinom fit'lerden ileride bir nokta seç, oraya yönelmek için
        gereken yanal sapmayı hesapla (Pure-Pursuit-Lite).

        bird-eye'da y=0 üst (uzak), y=bird_h alt (araç burnu).
        Lookahead = aracın burnundan base + speed*factor kadar üstte bir nokta.
        """
        if poly_l is None and poly_r is None:
            return None
        # Hıza orantılı lookahead (yüksek hızda ileri bak)
        la_dist = LOOKAHEAD_BASE_PX + LOOKAHEAD_SPEED_FACTOR * max(self.current_speed, 0.0)
        la_dist = float(np.clip(la_dist, 30.0, self.bird_h * 0.85))
        y_target = self.bird_h - la_dist  # bird-eye üst yönü = uzak
        y_target = float(np.clip(y_target, 0.0, self.bird_h - 1))

        if poly_l is not None and poly_r is not None:
            xl = float(np.polyval(poly_l, y_target))
            xr = float(np.polyval(poly_r, y_target))
            target_x = (xl + xr) / 2.0
        elif poly_l is not None:
            xl = float(np.polyval(poly_l, y_target))
            target_x = xl + self.last_lane_width / 2.0
        else:
            xr = float(np.polyval(poly_r, y_target))
            target_x = xr - self.last_lane_width / 2.0

        return float(self.mid - target_x)

    # ==================================================================
    # YARDIMCILAR
    # ==================================================================
    def _update_memory(self, side: str, peak: int, seen: bool) -> bool:
        """Hafızayı günceller; şerit hâlâ geçerliyse True döndürür."""
        attr = f'_{side}_mem'
        if seen:
            setattr(self, attr, (peak, 0))
            return True
        mem = getattr(self, attr)
        if mem is not None:
            col, age = mem
            if age < LANE_MEMORY_FRAMES:
                setattr(self, attr, (col, age + 1))
                return True
            setattr(self, attr, None)
        return False

    def _find_peak(self, histogram: np.ndarray,
                   lo: int, hi: int,
                   last_known: int | None) -> tuple:
        """[lo, hi) aralığında ağırlıklı tepe noktası bul.

        Döndürür: (tepe_sütunu, geçerli_mi, tepe_yüksekliği)
        """
        if last_known is not None:
            w_lo = max(lo, last_known - LANE_SEARCH_WINDOW)
            w_hi = min(hi, last_known + LANE_SEARCH_WINDOW)
        else:
            w_lo, w_hi = lo, hi

        region = histogram[w_lo:w_hi]
        total  = float(region.sum())
        peak_height = float(region.max()) if region.size else 0.0

        if total < MIN_LANE_SIGNAL:
            region = histogram[lo:hi]
            total  = float(region.sum())
            peak_height = float(region.max()) if region.size else 0.0
            if total < MIN_LANE_SIGNAL:
                fallback = last_known if last_known is not None else (lo + hi) // 2
                return fallback, False, peak_height
            centroid = int(np.average(np.arange(lo, hi), weights=region))
        else:
            centroid = int(np.average(np.arange(w_lo, w_hi), weights=region))

        return int(np.clip(centroid, lo, hi - 1)), True, peak_height

    def set_speed(self, speed: float) -> None:
        """Dışarıdan mevcut araç hızını set et (lookahead için)."""
        self.current_speed = float(speed)

    # ==================================================================
    # DEBUG GÖRSELLEŞTİRME
    # ==================================================================
    def _draw_debug(self, bird, mask,
                    near_lp, near_rp, near_lv, near_rv,
                    mid_lp=None, mid_rp=None,
                    far_lp=None, far_rp=None,
                    center=None, error=0, v_mean=0,
                    poly_l=None, poly_r=None, lookahead_err=None) -> np.ndarray:
        """Tüm bilgileri içeren debug görüntüsü."""
        debug = cv2.addWeighted(bird, 0.55,
                                cv2.cvtColor(mask, cv2.COLOR_GRAY2RGB), 0.45, 0)
        h     = self.bird_h
        far_h = int(h * LANE_FAR_RATIO)
        mid_end = int(h * (LANE_FAR_RATIO + LANE_MID_RATIO))

        # Polinom fit eğrileri (mor kalın çizgi)
        if poly_l is not None:
            self._draw_poly(debug, poly_l, (200, 80, 220))
        if poly_r is not None:
            self._draw_poly(debug, poly_r, (200, 80, 220))

        # UZAK ROI çizgileri (cyan, ince)
        if far_lp is not None:
            cv2.line(debug, (far_lp, 0), (far_lp, far_h), (0, 200, 220), 1)
        if far_rp is not None:
            cv2.line(debug, (far_rp, 0), (far_rp, far_h), (0, 200, 220), 1)
        # ORTA ROI (sarı)
        if mid_lp is not None:
            cv2.line(debug, (mid_lp, far_h), (mid_lp, mid_end), (0, 220, 220), 2)
        if mid_rp is not None:
            cv2.line(debug, (mid_rp, far_h), (mid_rp, mid_end), (0, 220, 220), 2)
        # YAKIN ROI (yeşil kalın)
        if near_lv:
            cv2.line(debug, (near_lp, mid_end), (near_lp, h), (0, 220, 0), 2)
        if near_rv:
            cv2.line(debug, (near_rp, mid_end), (near_rp, h), (0, 220, 0), 2)

        # Şerit merkezi & kare merkezi
        if center is not None:
            cv2.line(debug, (center, 0), (center, h), (255, 60, 0), 2)
        cv2.line(debug, (self.mid, 0), (self.mid, h), (0, 80, 255), 1)

        # Lookahead noktası
        if poly_l is not None or poly_r is not None:
            la_dist = LOOKAHEAD_BASE_PX + LOOKAHEAD_SPEED_FACTOR * max(self.current_speed, 0.0)
            la_dist = float(np.clip(la_dist, 30.0, h * 0.85))
            y_t = int(np.clip(h - la_dist, 0, h - 1))
            if poly_l is not None and poly_r is not None:
                xt = int((np.polyval(poly_l, y_t) + np.polyval(poly_r, y_t)) / 2)
            elif poly_l is not None:
                xt = int(np.polyval(poly_l, y_t) + self.last_lane_width / 2)
            else:
                xt = int(np.polyval(poly_r, y_t) - self.last_lane_width / 2)
            cv2.circle(debug, (int(np.clip(xt, 0, self.bird_w - 1)), y_t),
                       8, (255, 200, 0), 2)

        # ROI ayırıcı çizgiler
        cv2.line(debug, (0, far_h),  (self.bird_w, far_h),  (90, 90, 90), 1)
        cv2.line(debug, (0, mid_end),(self.bird_w, mid_end),(90, 90, 90), 1)

        # Üst bilgi paneli
        cv2.putText(debug, f"err:{error:+d}px  V:{v_mean:.0f}  W:{self.last_lane_width:.0f}",
                    (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 230, 0), 2)
        cv2.putText(debug, f"{self.last_status}", (8, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 200, 200), 1)
        conf = self.last_confidence
        cv2.putText(debug,
                    f"conf N:{conf['near']:.2f} M:{conf['mid']:.2f} F:{conf['far']:.2f}",
                    (8, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)
        if lookahead_err is not None:
            cv2.putText(debug, f"LA:{lookahead_err:+.0f}", (8, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 200, 100), 1)
        if not self._calib_done:
            cv2.putText(debug, f"KALIBRASYON {self._calib_frames}/{AUTO_HSV_CALIB_FRAMES}",
                        (8, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        return debug

    def _draw_poly(self, img: np.ndarray, coeffs: np.ndarray, color: tuple) -> None:
        """Polinom eğrisini görüntüye çiz."""
        ys = np.linspace(0, self.bird_h - 1, 30, dtype=np.int32)
        xs = np.polyval(coeffs, ys.astype(np.float32)).astype(np.int32)
        xs = np.clip(xs, 0, self.bird_w - 1)
        pts = np.stack([xs, ys], axis=1).reshape(-1, 1, 2)
        cv2.polylines(img, [pts], False, color, 2)

    def _blank_debug(self, bird: np.ndarray, mask: np.ndarray) -> np.ndarray:
        debug = cv2.addWeighted(bird, 0.6,
                                cv2.cvtColor(mask, cv2.COLOR_GRAY2RGB), 0.4, 0)
        cv2.putText(debug, "SERIT YOK",
                    (self.bird_w // 2 - 70, self.bird_h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 0, 0), 2)
        return debug

    # ------------------------------------------------------------------
    def update_clahe(self, clip: float, tile: int) -> None:
        """Çalışma zamanında CLAHE parametrelerini günceller (tune.py için)."""
        self._clahe = cv2.createCLAHE(
            clipLimit=float(clip),
            tileGridSize=(int(tile), int(tile)),
        )

    def reset_polynomials(self) -> None:
        """Polinom geçmişini sıfırla (örn. duraklamadan sonra)."""
        self._poly_left = None
        self._poly_right = None
        self._ema_error = None
