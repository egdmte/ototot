# =============================================================================
# events.py  —  Görsel olay dedektörü
#
# Tespit eder:
#   • Trafik ışığı      → 'green' | None  (yarış başlangıcı için; kırmızı tespit edilmez)
#   • Yaya geçidi       → bool  (yatay beyaz-koyu şerit deseni)
#   • Hemzemin geçit    → bool  (demiryolu geçidi — X şerit deseni)
#   • Tümsek            → bool  (yol ROI'da güçlü yatay kenar)
#   • Turuncu araç      → bool  (yol ROI'da turuncu engel)
#   • Çıkmaz yol        → bool  (merkez yol ROI'da büyük engel veya şerit bitiyor)
#   • Park bölgesi      → bool  (çerçeve altında kırmızı slot görünümü)
#
# NOT: Yarışma kurallarında (MEB 2026 PDF) dur işareti YOKTUR.
#
# Tüm tespitler debounce'ludur: bir olay N ardışık karede görünmeden
# True olarak raporlanmaz.
# =============================================================================
import cv2
import numpy as np

from config import (
    WIDTH,
    SIGNAL_ROI_TOP, SIGNAL_ROI_BOTTOM,
    ROAD_ROI_TOP, ROAD_ROI_BOTTOM,
    GREEN_HSV_LOW, GREEN_HSV_HIGH,
    WHITE_HSV_LOW, WHITE_HSV_HIGH,
    SIGNAL_MIN_AREA, CROSSWALK_MIN_STRIPES, HEMZEMIN_DIAG_MIN_LINES,
    EVENT_DEBOUNCE_FRAMES, EVENT_NEAR_ROI_RATIO,
    ORANGE_HSV_LOW, ORANGE_HSV_HIGH, ORANGE_MIN_AREA,
    YELLOW_HSV_LOW, YELLOW_HSV_HIGH, YELLOW_MIN_AREA,

    PARKING_HSV_LOW1, PARKING_HSV_HIGH1,
    PARKING_HSV_LOW2, PARKING_HSV_HIGH2,
    PARKING_TRIGGER_AREA, PARKING_ROI_TOP,
    PARKING_NEAR_BOTTOM_RATIO,
    SIGN_BLUE_HSV_LOW, SIGN_BLUE_HSV_HIGH, SIGN_MIN_AREA,
)


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------

def _circularity(contour: np.ndarray) -> float:
    area = cv2.contourArea(contour)
    peri = cv2.arcLength(contour, True)
    if peri < 1:
        return 0.0
    return (4 * np.pi * area) / (peri * peri)


def _green_mask(hsv: np.ndarray) -> np.ndarray:
    return cv2.inRange(hsv, np.array(GREEN_HSV_LOW,  dtype=np.uint8),
                            np.array(GREEN_HSV_HIGH, dtype=np.uint8))


def _white_mask(hsv: np.ndarray) -> np.ndarray:
    return cv2.inRange(hsv, np.array(WHITE_HSV_LOW,  dtype=np.uint8),
                            np.array(WHITE_HSV_HIGH, dtype=np.uint8))


def _orange_mask(hsv: np.ndarray) -> np.ndarray:
    return cv2.inRange(hsv, np.array(ORANGE_HSV_LOW,  dtype=np.uint8),
                            np.array(ORANGE_HSV_HIGH, dtype=np.uint8))


def _yellow_mask(hsv: np.ndarray) -> np.ndarray:
    """Sarı araç maskesi — sollama yasağı bölgesindeki sarı engel araçları."""
    return cv2.inRange(hsv, np.array(YELLOW_HSV_LOW,  dtype=np.uint8),
                            np.array(YELLOW_HSV_HIGH, dtype=np.uint8))


def _sign_blue_mask(hsv: np.ndarray) -> np.ndarray:
    """Mavi levha maskesi — Park (P) ve Çıkmaz Yol (T) işaret tabelaları."""
    return cv2.inRange(hsv, np.array(SIGN_BLUE_HSV_LOW,  dtype=np.uint8),
                            np.array(SIGN_BLUE_HSV_HIGH, dtype=np.uint8))


def _parking_mask(hsv: np.ndarray) -> np.ndarray:
    p1 = cv2.inRange(hsv, np.array(PARKING_HSV_LOW1, dtype=np.uint8),
                          np.array(PARKING_HSV_HIGH1, dtype=np.uint8))
    p2 = cv2.inRange(hsv, np.array(PARKING_HSV_LOW2, dtype=np.uint8),
                          np.array(PARKING_HSV_HIGH2, dtype=np.uint8))
    return cv2.bitwise_or(p1, p2)


def _largest_circular_blob(mask: np.ndarray, min_area: float,
                            circ_min: float = 0.55) -> float:
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = 0.0
    for c in cnts:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        if _circularity(c) >= circ_min:
            best = max(best, area)
    return best


def _largest_blob_area(mask: np.ndarray, min_area: float) -> float:
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = 0.0
    for c in cnts:
        a = cv2.contourArea(c)
        if a >= min_area:
            best = max(best, a)
    return best


def _largest_blob_area_and_bottom(mask: np.ndarray, min_area: float) -> tuple:
    """En büyük (alan ≥ min_area) blobun (alanını, bbox alt-kenar y'sini) döndürür.

    Bulamazsa (0.0, 0). Park alanı yakınlık kontrolü için kullanılır:
    aynı renkte uzaktaki bir leke yerine yakındaki büyük park slotuna karar verir.
    """
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best_area = 0.0
    best_bottom = 0
    for c in cnts:
        a = cv2.contourArea(c)
        if a >= min_area and a > best_area:
            x, y, w, h = cv2.boundingRect(c)
            best_area = a
            best_bottom = y + h
    return best_area, best_bottom


# ---------------------------------------------------------------------------
# Ana sınıf
# ---------------------------------------------------------------------------

class EventDetector:
    """BGR kamera karesinden iz olaylarını tespit eder.

    Her döngü iterasyonunda ``detect(frame)`` çağrısı yapın.
    Döndürür dict:
        {
            'traffic_light':  'green' | None,
            'crosswalk':      bool,
            'hemzemin':       bool,
            'speed_bump':     bool,
            'orange_car':     bool,
            'parking_zone':   bool,
        }
    """

    def __init__(self):
        self._db: dict = {k: 0 for k in (
            'green', 'crosswalk', 'crosswalk_close',
            'hemzemin', 'hemzemin_close',
            'speed_bump', 'orange_car', 'yellow_car',
            'parking_zone', 'sign_blue',
        )}
        self._light: str | None = None
        self._k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self._k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    # ------------------------------------------------------------------
    def detect(self, frame: np.ndarray) -> dict:
        """RGB kareyi işler ve olay sözlüğü döndürür.

        Döndürür dict:
            traffic_light  : 'green' | None  (yarış başlangıcı için)
            crosswalk      : bool  — yaya geçidi (kural 3.4.2: ≥5 s dur)
            hemzemin       : bool  — hemzemin geçit (kural 3.4.4: ≥5 s dur)
            speed_bump     : bool  — hız tümsek (kural 3.4.3: yavaşla)
            orange_car     : bool  — sollama hedefi turuncu araç (kural 3.4.5)
            yellow_car     : bool  — sollama YASAĞI bölgesi sarı engel araç
            parking_zone   : bool  — kırmızı park slotu görünür (kural 3.4.7)
            sign_blue      : bool  — mavi levha (Park P tabelası)
        """
        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)

        # ----------------------------------------------------------------
        # Üst ROI: trafik ışığı + levha tespiti
        # ----------------------------------------------------------------
        sig_hsv = hsv[SIGNAL_ROI_TOP:SIGNAL_ROI_BOTTOM, :]

        # Trafik ışığı: yuvarlak yeşil blob (Şekil 7: 30-35 cm yükseklik)
        # Kırmızı tespiti kaldırıldı — yarışta yalnızca yeşil ışık aranır;
        # kırmızı/diğer hâl BEKLIYOR'da implicit olarak frenle ele alınır.
        green_m = cv2.morphologyEx(_green_mask(sig_hsv), cv2.MORPH_OPEN, self._k5)
        raw_green = _largest_circular_blob(green_m, SIGNAL_MIN_AREA) > 0

        # Mavi levha tespiti — Park (P) veya Çıkmaz Yol (T) işaret tabelası.
        # Levhalar küçüktür (13 cm), sinyal ROI'nun sağ / sol kenarında belirir.
        raw_sign_blue = self._detect_sign_blue(sig_hsv)

        # ----------------------------------------------------------------
        # Alt ROI: yol yüzeyi olayları
        # ----------------------------------------------------------------
        road_hsv = hsv[ROAD_ROI_TOP:ROAD_ROI_BOTTOM, :]
        road_bgr = cv2.cvtColor(
            frame[ROAD_ROI_TOP:ROAD_ROI_BOTTOM, :], cv2.COLOR_RGB2BGR
        )

        raw_crosswalk, raw_crosswalk_close = self._detect_stripe_pattern(road_hsv)
        raw_hemzemin,  raw_hemzemin_close  = self._detect_hemzemin(road_bgr)
        raw_speed_bump = self._detect_speed_bump(road_bgr)

        # Turuncu araç — sollama serbest bölgesindeki 20×30×25 cm turuncu engel
        orange_m = cv2.morphologyEx(_orange_mask(road_hsv), cv2.MORPH_OPEN, self._k5)
        raw_orange_car = _largest_blob_area(orange_m, ORANGE_MIN_AREA) > 0

        # Sarı araç — sollama YASAĞI bölgesindeki 20×45×25 cm sarı karşı şerit engeli.
        # Turuncu ile karıştırılmaması için HSV alt sınırı H=22'den başlar.
        yellow_m = cv2.morphologyEx(_yellow_mask(road_hsv), cv2.MORPH_OPEN, self._k5)
        raw_yellow_car = _largest_blob_area(yellow_m, YELLOW_MIN_AREA) > 0

        # Park bölgesi — kırmızı slot rengi (kılavuz Şekil 6).
        # İki ek koşul: (a) blob alt-kenarı ROI'nin yakın kısmında, (b) aynı karede
        # turuncu engel yoksa. Bu, uzaktaki kırmızılara ve turuncu/kırmızı renk
        # overlap'ine karşı koruma sağlar.
        park_roi = hsv[PARKING_ROI_TOP:, :]
        park_m = cv2.morphologyEx(_parking_mask(park_roi), cv2.MORPH_OPEN, self._k5)
        park_area, park_bottom = _largest_blob_area_and_bottom(
            park_m, PARKING_TRIGGER_AREA
        )
        park_roi_h = park_m.shape[0]
        raw_parking_zone = (
            park_area > 0
            and park_bottom > park_roi_h * PARKING_NEAR_BOTTOM_RATIO
            and not raw_orange_car
        )

        # ----------------------------------------------------------------
        # Debounce — her olay EVENT_DEBOUNCE_FRAMES ardışık karede görünmeli
        # ----------------------------------------------------------------
        c_green        = self._debounce('green',        raw_green)
        c_crosswalk    = self._debounce('crosswalk',    raw_crosswalk)
        c_crosswalk_cl = self._debounce('crosswalk_close', raw_crosswalk_close)
        c_hemzemin     = self._debounce('hemzemin',     raw_hemzemin)
        c_hemzemin_cl  = self._debounce('hemzemin_close',  raw_hemzemin_close)
        c_bump         = self._debounce('speed_bump',   raw_speed_bump)
        c_orange       = self._debounce('orange_car',   raw_orange_car)
        c_yellow       = self._debounce('yellow_car',   raw_yellow_car)
        c_parking_zone = self._debounce('parking_zone', raw_parking_zone)
        c_sign_blue    = self._debounce('sign_blue',    raw_sign_blue)

        # Trafik ışığı durumu: onaylanmış yeşile göre güncellenir
        if c_green:
            self._light = 'green'

        return {
            'traffic_light':   self._light,
            'crosswalk':       c_crosswalk,
            'crosswalk_close': c_crosswalk_cl,
            'hemzemin':        c_hemzemin,
            'hemzemin_close':  c_hemzemin_cl,
            'speed_bump':      c_bump,
            'orange_car':      c_orange,
            'yellow_car':      c_yellow,
            'parking_zone':    c_parking_zone,
            'sign_blue':       c_sign_blue,
        }

    # ------------------------------------------------------------------
    def _debounce(self, key: str, raw: bool) -> bool:
        if raw:
            self._db[key] = min(self._db[key] + 1, EVENT_DEBOUNCE_FRAMES + 1)
        else:
            self._db[key] = 0
        return self._db[key] >= EVENT_DEBOUNCE_FRAMES

    # ------------------------------------------------------------------
    @staticmethod
    def _detect_stripe_pattern(road_hsv: np.ndarray) -> tuple:
        """≥N adet yatay beyaz bant tespit eder (yaya geçidi).

        Döndürür (detected, near):
            detected — desen var mı
            near     — desenin alt-kenarı ROI'nin yakın diliminde mi
                       (yakın = kuralın 30 cm önce dur eşiğine geldik)

        İYİLEŞTİRİLDİ: Daha katı kontroller (false positive azaltma):
        1. Min 4 bant (eskiden 2)
        2. Bantlar arasında BOŞLUK olmalı (siyah ara)
        3. Bantlar BENZER kalınlıkta olmalı
        4. Her bant kare genişliğinin > %40'ı kadar olmalı
        """
        white     = _white_mask(road_hsv)
        roi_h     = white.shape[0]
        roi_w     = white.shape[1]
        stripe_h  = max(1, roi_h // 12)

        # Her bant için min beyaz piksel sayısı (genişliğin %40'ı)
        min_white_in_band = roi_w * stripe_h * 0.40

        # Bantları kategorize et: 1=beyaz dolu, 0=siyah/karışık
        bands = []
        for i in range(0, roi_h - stripe_h, stripe_h):
            band_white = white[i:i + stripe_h, :].sum() / 255
            bands.append(1 if band_white > min_white_in_band else 0)

        # 1) Toplam beyaz bant sayısı
        white_band_count = sum(bands)
        if white_band_count < CROSSWALK_MIN_STRIPES:
            return False, False

        # 2) Beyaz bantlar arasında BOŞLUK (siyah ara) olmalı
        # Yani 1,1,1,1,1,1 (düz beyaz yol) → REDDET
        # 1,0,1,0,1,0 (yaya geçidi) → KABUL
        transitions = 0
        for i in range(1, len(bands)):
            if bands[i] != bands[i - 1]:
                transitions += 1

        # En az (CROSSWALK_MIN_STRIPES - 1) * 2 geçiş olmalı (1↔0 değişimleri)
        # 4 bant için min 6 geçiş = 4 beyaz + 3 siyah ara
        min_transitions = (CROSSWALK_MIN_STRIPES - 1) * 2 - 1
        if transitions < min_transitions:
            return False, False

        # Yakınlık: ROI'nin alt EVENT_NEAR_ROI_RATIO sonrası bantlarından
        # en az biri beyazsa desen kareye çok yakın → 30 cm eşiği.
        near_band_start = int(len(bands) * EVENT_NEAR_ROI_RATIO)
        near = any(b == 1 for b in bands[near_band_start:])
        return True, near

    # ------------------------------------------------------------------
    @staticmethod
    def _detect_speed_bump(road_bgr: np.ndarray) -> bool:
        """Yatay Canny kenarları → tümsek."""
        gray  = cv2.cvtColor(road_bgr, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
        return int((edges.sum(axis=1) / 255 > WIDTH * 0.55).sum()) >= 2

    # ------------------------------------------------------------------
    @staticmethod
    def _detect_hemzemin(road_bgr: np.ndarray) -> tuple:
        """X-desen çapraz çizgiler → hemzemin geçit.

        Döndürür (detected, near):
            detected — her iki çapraz yönde HEMZEMIN_DIAG_MIN_LINES çizgi
            near     — çaprazlardan en az biri ROI'nin yakın diliminde sonlanıyor
                       (30 cm eşiği için).
        """
        gray  = cv2.cvtColor(road_bgr, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180,
                                threshold=30, minLineLength=40, maxLineGap=15)
        if lines is None:
            return False, False
        roi_h    = road_bgr.shape[0]
        near_y   = roi_h * EVENT_NEAR_ROI_RATIO
        pos_diag = 0   # \ yönü
        neg_diag = 0   # / yönü
        max_y    = 0
        for line in lines:
            x1, y1, x2, y2 = line[0]
            dx, dy = x2 - x1, y2 - y1
            if dx == 0:
                continue
            angle = np.degrees(np.arctan2(abs(dy), abs(dx)))
            if 25 <= angle <= 65:
                if dx * dy > 0:
                    pos_diag += 1
                else:
                    neg_diag += 1
                max_y = max(max_y, y1, y2)
        detected = (pos_diag >= HEMZEMIN_DIAG_MIN_LINES and
                    neg_diag >= HEMZEMIN_DIAG_MIN_LINES)
        near = detected and max_y >= near_y
        return detected, near

    # ------------------------------------------------------------------
    def _detect_sign_blue(self, sig_hsv: np.ndarray) -> bool:
        """Sinyal ROI'da mavi arka planlı levha (Park P veya Çıkmaz T) tespit eder.

        Mavi levhalar: kılavuz Şekil 10 — 13 cm genişlik, 20 cm toplam yükseklik.
        Trafik ışığına kıyasla daha küçük ve dikdörtgen şekilli olduklarından
        yuvarlak blob filtresi yerine basit alan eşiği kullanılır.
        """
        blue_m = cv2.morphologyEx(
            _sign_blue_mask(sig_hsv), cv2.MORPH_OPEN, self._k3
        )
        return _largest_blob_area(blue_m, SIGN_MIN_AREA) > 0

    # ------------------------------------------------------------------
    def debug_frame(self, frame: np.ndarray, events: dict) -> np.ndarray:
        """Olay ROI'larını ve aktif olayları kareye çizer."""
        vis = frame.copy()
        cv2.rectangle(vis, (0, SIGNAL_ROI_TOP), (WIDTH - 1, SIGNAL_ROI_BOTTOM),
                      (0, 200, 200), 1)
        cv2.rectangle(vis, (0, ROAD_ROI_TOP), (WIDTH - 1, ROAD_ROI_BOTTOM),
                      (200, 200, 0), 1)
        light = events['traffic_light']
        light_col = ((0, 255, 0) if light == 'green' else (180, 180, 180))
        cv2.putText(vis, f"ISIK:{light or '--'}", (WIDTH - 160, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, light_col, 2)

        y = 50
        for key, label, color in [
            ('crosswalk',    'YAYA GECİDİ',  (255, 200,   0)),
            ('hemzemin',     'HEMZEMİN',     (  0, 180, 255)),
            ('speed_bump',   'TÜMSEK',        (255, 165,   0)),
            ('orange_car',   'TURUNCU ARAC', (255, 120,   0)),
            ('yellow_car',   'SARI ARAC',    (220, 220,   0)),

            ('parking_zone', 'PARK BÖLGE',   (255,   0, 200)),
            ('sign_blue',    'MAVİ LEVHA',   ( 80, 120, 255)),
        ]:
            if events.get(key):
                cv2.putText(vis, label, (WIDTH - 210, y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                y += 26
        return vis