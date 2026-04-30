# =============================================================================
# main.py  —  Otonom şerit takip ana giriş noktası (BASİT VERSİYON)
#
# Özellikler:
#   - Web sitesi YOK (sadece CMD/terminal)
#   - GG, EZ veya EFN yazınca araç başlar (yeşil ışık simüle)
#   - SPACE (boşluk) tuşu = HEMEN başlat (anında, tek tuş)
#   - Q tuşu = programdan çık
#   - GPIO 16 buton kaldırıldı
#
# Kullanım: python main.py
# =============================================================================
import os
import signal
import sys
import termios
import threading
import time
import tty

import cv2
import numpy as np

# Kamera: Pi'de picamera2, geliştirme/test için OpenCV VideoCapture
try:
    from picamera2 import Picamera2
    _USE_PICAMERA = True
except ImportError:
    _USE_PICAMERA = False
    print("[main] picamera2 bulunamadı — OpenCV VideoCapture kullanılıyor (geliştirme modu)")

# GPIO buton: Pi'de gpiozero.Button, yoksa sessizce skip (geliştirme modu).
# Bu try/except sayesinde Pi olmadan da kod çalışır; buton beklenmez.
try:
    from gpiozero import Button as _GpioButton
    _HAS_BUTTON = True
except ImportError:
    _GpioButton = None  # type: ignore[assignment]
    _HAS_BUTTON = False

from config import (
    WIDTH, HEIGHT,
    CROSSWALK_WAIT_SEC, HEMZEMIN_WAIT_SEC,
    SPEED_BUMP_SLOW_SEC, SPEED_BUMP_SPEED,
    APPROACH_SPEED, APPROACH_TIMEOUT_SEC,
    OVERTAKING_STEER_BIAS, OVERTAKING_CROSS_SEC,
    OVERTAKING_PASS_SEC, OVERTAKING_RETURN_SEC, OVERTAKING_SPEED,

    PARKING_HSV_LOW1, PARKING_HSV_HIGH1,
    PARKING_HSV_LOW2, PARKING_HSV_HIGH2,
    PARKING_MIN_AREA, PARKING_ROI_TOP,
    PARKING_SPEED, PARKING_CENTER_TOL,
    CAMERA_BGR_OUTPUT, CAMERA_ROTATE_180, SHOW_PREVIEW,
    LANE_LOST_TURN_SEC, LANE_LOST_TURN_BIAS,
    START_BUTTON_PIN,
)
from controller import PDController
from events import EventDetector
from logger import ErrorLogger, DiagLogger
from motor import MotorDriver

# Lane detector secimi
from config import (
    USE_SIMPLE_LANE, SIMPLE_LANE_INVERT,
    USE_LANE_CENTER, LANE_CENTER_INVERT,
    USE_LANE_WINDOW, LANE_WINDOW_INVERT,
)

if USE_LANE_WINDOW:
    from lane_window import LaneWindowDetector as LaneDetector
    print("[main] LANE WINDOW aktif (3 bolgeli olu bolge - ONERILEN)")
elif USE_LANE_CENTER:
    from lane_center import LaneCenterDetector as LaneDetector
    print("[main] LANE CENTER aktif (IKI SERIT ARASI SIYAH YOL)")
elif USE_SIMPLE_LANE:
    from simple_lane import SimpleLaneDetector as LaneDetector
    print("[main] BASIT LANE DETECTOR aktif (Otsu + Center of Mass)")
else:
    from lane import LaneDetector
    print("[main] Karmasik lane detector aktif (3 ROI)")


# ---------------------------------------------------------------------------
# Kamera sarmalayıcı
# ---------------------------------------------------------------------------
class _Camera:
    def __init__(self):
        self._latest:  np.ndarray | None = None
        self._lock    = threading.Lock()
        self._running = True

        if _USE_PICAMERA:
            self._pi = Picamera2()
            cfg = self._pi.create_preview_configuration(
                main={"format": "RGB888", "size": (WIDTH, HEIGHT)},
                buffer_count=4,          # starvation önleme
            )
            self._pi.configure(cfg)
            self._pi.start()
            time.sleep(2)                # AWB ısınma
            threading.Thread(target=self._loop, daemon=True).start()
        else:
            self._cv = cv2.VideoCapture(0)
            self._cv.set(cv2.CAP_PROP_FRAME_WIDTH,  WIDTH)
            self._cv.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)

    def _loop(self) -> None:
        """Kameradan sürekli kare çeken arka plan thread'i.

        Ana döngü ne kadar yavaş işlerse işlesin kamera pipeline'ı
        boşta kalmaz; buffer I/O hatası önlenir.
        """
        while self._running:
            try:
                frame = self._pi.capture_array()
                # Pi 5 / yeni libcamera: RGB888 bazen XRGB8888 (4 kanal) gelir
                if frame.ndim == 3 and frame.shape[2] == 4:
                    frame = frame[:, :, :3]
                frame = frame.copy()     # DMA buffer sahipliğini al
                if CAMERA_BGR_OUTPUT:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                if CAMERA_ROTATE_180:
                    frame = cv2.rotate(frame, cv2.ROTATE_180)
                with self._lock:
                    self._latest = frame
            except Exception:
                pass

    def capture(self) -> np.ndarray:
        if _USE_PICAMERA:
            with self._lock:
                if self._latest is not None:
                    return self._latest
            return np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        else:
            ret, frame = self._cv.read()
            if not ret:
                return np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            if CAMERA_ROTATE_180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            return frame

    def stop(self):
        self._running = False
        if _USE_PICAMERA:
            time.sleep(0.1)
            self._pi.stop()
        else:
            self._cv.release()


# ---------------------------------------------------------------------------
# Bileşenler
# ---------------------------------------------------------------------------
camera         = _Camera()

# Lane detector olustur (invert parametreli versiyonlar icin)
if USE_LANE_WINDOW:
    lane_detector = LaneDetector(invert_steering=LANE_WINDOW_INVERT)
elif USE_LANE_CENTER:
    lane_detector = LaneDetector(invert_steering=LANE_CENTER_INVERT)
elif USE_SIMPLE_LANE:
    lane_detector = LaneDetector(invert_steering=SIMPLE_LANE_INVERT)
else:
    lane_detector = LaneDetector()

controller     = PDController()
motor          = MotorDriver()
logger         = ErrorLogger()
diag           = DiagLogger()  # her surusten ayri diag_<timestamp>.csv
event_detector = EventDetector()


# ---------------------------------------------------------------------------
# Global durum değişkenleri
# ---------------------------------------------------------------------------
_running         = True
_state           = 'BEKLIYOR'
_state_timer     = 0.0
_ovt_phase       = 0
_manual_green    = False   # GG/EZ/SPACE/buton ile yeşil ışık simülasyonu
_lane_lost_time: float | None = None   # şerit kayıp failsafe zamanlayıcısı

# Yarış zaman tracking (Görev/PDF 4.4: 240 sn üst sınır + bitirme katsayısı)
_race_start_time: float | None = None
_finish_printed       = False
_time_warning_printed = False
_button_handle = None      # gpiozero.Button referansı (shutdown'da close)

# Tabela tabanlı sollama yasağı
_NO_OVERTAKE_SEC = 8.0          # sollamabam tabelası sonrası yasak süresi
_no_overtake_until: float = 0.0 # bu zamana kadar sollama yapma

# HSV Kalibrasyon modu (C tuşu ile aktif)
_hsv_calib_active = False
_hsv_calib_roi_list = []  # [(x1,y1,x2,y2), ...]
_hsv_calib_drawing = False
_hsv_calib_start = (0, 0)
_hsv_calib_low = None
_hsv_calib_high = None
_hsv_calib_window = "HSV Kalibrasyon - C:hesapla S:kaydet Q:cik"


# ---------------------------------------------------------------------------
# Klavye dinleme thread'i (raw mode — tek tuş)
# ---------------------------------------------------------------------------
def keyboard_listener():
    """Ayrı thread'de klavye dinler. GG, EZ, EFN veya SPACE = başlat."""
    global _manual_green, _running, _hsv_calib_active
    
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    
    try:
        # cbreak mode — tek tuş okuma (ENTER gerekli değil)
        tty.setcbreak(fd)
        
        buffer = ""
        
        while _running:
            ch = sys.stdin.read(1)
            
            if not ch:
                continue
            
            # Çıkış tuşu
            if ch == 'q' or ch == 'Q':
                print("\n[KLAVYE] Q basıldı — Çıkılıyor...")
                _running = False
                break
            
            # SPACE (boşluk) = anında başlat
            if ch == ' ':
                if not _manual_green:
                    print("\n[KLAVYE] SPACE basıldı — YEŞİL IŞIK! 🚦")
                    _manual_green = True
                continue
            
            # C = HSV Kalibrasyon modu (interaktif ROI)
            if ch == 'c' or ch == 'C':
                global _hsv_calib_active
                if not _hsv_calib_active:
                    _hsv_calib_active = True
                    print("\n[KLAVYE] C basıldı — HSV KALIBRASYON MODU aktif")
                    print("[kalibrasyon] Fare ile beyaz serit uzerine ROI ciz")
                    print("[kalibrasyon] C=hesapla, S=kaydet, Q=kalibrasyondan cik")
                continue
            
            # Karakter buffer'a ekle (büyük harfe çevir)
            buffer += ch.upper()
            
            # Buffer çok büyükse kısalt
            if len(buffer) > 10:
                buffer = buffer[-10:]
            
            # GG, EZ veya EFN kontrol
            if buffer.endswith("GG") or buffer.endswith("EZ"):
                cmd = buffer[-2:]
                if not _manual_green:
                    print(f"\n[KLAVYE] '{cmd}' yazıldı — YEŞİL IŞIK! 🚦")
                    _manual_green = True
                buffer = ""
            elif buffer.endswith("EFN"):
                if not _manual_green:
                    print("\n[KLAVYE] 'EFN' yazıldı — YEŞİL IŞIK! 🚦")
                    _manual_green = True
                buffer = ""
    
    except Exception as e:
        print(f"\n[KLAVYE] Hata: {e}")
    finally:
        # Terminal'i normal moda döndür
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Yön yardımcısı
# ---------------------------------------------------------------------------
def _apply_dir(left: float, right: float) -> tuple:
    """Direksiyon değerlerini motorlara uygulamaya hazırla."""
    return left, right


# ---------------------------------------------------------------------------
# HSV Kalibrasyon Yardımcıları
# ---------------------------------------------------------------------------
def _hsv_mouse_callback(event, x, y, flags, param):
    """HSV kalibrasyon penceresi için mouse callback."""
    global _hsv_calib_drawing, _hsv_calib_start, _hsv_calib_roi_list
    
    if event == cv2.EVENT_LBUTTONDOWN:
        _hsv_calib_drawing = True
        _hsv_calib_start = (x, y)
    elif event == cv2.EVENT_MOUSEMOVE and _hsv_calib_drawing:
        pass  # Görsel geribildirim için gerekirse eklenebilir
    elif event == cv2.EVENT_LBUTTONUP:
        _hsv_calib_drawing = False
        x1, y1 = _hsv_calib_start
        x2, y2 = x, y
        # Normalize (sol-ust sag-alt)
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        if abs(x2 - x1) > 10 and abs(y2 - y1) > 10:
            _hsv_calib_roi_list.append((x1, y1, x2, y2))
            print(f"[kalibrasyon] ROI eklendi: ({x1},{y1})-({x2},{y2})")

def _compute_hsv_bounds(frame_rgb: np.ndarray) -> tuple | None:
    """Toplanan ROI'lerden HSV low/high degerlerini hesapla."""
    global _hsv_calib_roi_list
    
    if not _hsv_calib_roi_list:
        return None
    
    hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
    samples = []
    
    for (x1, y1, x2, y2) in _hsv_calib_roi_list:
        roi = hsv[y1:y2, x1:x2]
        if roi.size > 0:
            samples.append(roi.reshape(-1, 3))
    
    if not samples:
        return None
    
    all_samples = np.vstack(samples)
    if len(all_samples) < 100:
        return None
    
    # Persentil bazli hesaplama (aykiri degerleri at)
    p5 = np.percentile(all_samples, 5, axis=0)
    p95 = np.percentile(all_samples, 95, axis=0)
    
    # Margin ekle
    h_low, s_low, v_low = p5[0], max(0, p5[1] - 10), max(0, p5[2] - 15)
    h_high, s_high, v_high = p95[0], min(255, p95[1] + 15), min(255, p95[2] + 20)
    
    return (int(h_low), int(s_low), int(v_low)), (int(h_high), int(s_high), int(v_high))

def _draw_hsv_overlay(frame_bgr: np.ndarray) -> np.ndarray:
    """Kalibrasyon overlay'ini ciz."""
    global _hsv_calib_roi_list, _hsv_calib_low, _hsv_calib_high
    
    display = frame_bgr.copy()
    
    # ROI dikdortgenleri
    for i, (x1, y1, x2, y2) in enumerate(_hsv_calib_roi_list):
        color = (0, 255, 0) if i == len(_hsv_calib_roi_list) - 1 else (0, 150, 0)
        cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
        cv2.putText(display, str(i+1), (x1+3, y1+18),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
    
    # Bilgi metni
    cv2.putText(display, "HSV KALIBRASYON", (10, 30),
               cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    cv2.putText(display, f"ROI: {len(_hsv_calib_roi_list)} | C:hesapla S:kaydet Q:cik",
               (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    
    if _hsv_calib_low and _hsv_calib_high:
        low_str = f"LOW:{_hsv_calib_low}"
        high_str = f"HIGH:{_hsv_calib_high}"
        cv2.putText(display, low_str, (10, 80),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        cv2.putText(display, high_str, (10, 100),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    
    return display


# ---------------------------------------------------------------------------
# Sollama alt durum makinesi (3 aşamalı)
# ---------------------------------------------------------------------------
def _run_overtaking(error, now: float) -> None:
    global _state, _ovt_phase, _state_timer
    
    elapsed = now - _state_timer
    
    if _ovt_phase == 0:
        eff_error = (error or 0) - OVERTAKING_STEER_BIAS
        l, r = controller.compute(eff_error)
        scale = OVERTAKING_SPEED / max(abs(l), abs(r), 1)
        motor.set_speed(*_apply_dir(l * scale, r * scale))
        if elapsed >= OVERTAKING_CROSS_SEC:
            _ovt_phase = 1
            _state_timer = now
    elif _ovt_phase == 1:
        l, r = controller.compute(error)
        scale = OVERTAKING_SPEED / max(abs(l), abs(r), 1)
        motor.set_speed(*_apply_dir(l * scale, r * scale))
        if elapsed >= OVERTAKING_PASS_SEC:
            _ovt_phase = 2
            _state_timer = now
    elif _ovt_phase == 2:
        eff_error = (error or 0) + OVERTAKING_STEER_BIAS
        l, r = controller.compute(eff_error)
        scale = OVERTAKING_SPEED / max(abs(l), abs(r), 1)
        motor.set_speed(*_apply_dir(l * scale, r * scale))
        if elapsed >= OVERTAKING_RETURN_SEC:
            _state = 'SURUYOR'
            _ovt_phase = 0
            controller.reset()


# ---------------------------------------------------------------------------
# Park etme
# ---------------------------------------------------------------------------
def _run_parking(frame: np.ndarray, error) -> None:
    global _state
    
    hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
    roi = hsv[PARKING_ROI_TOP:, :]
    
    m1 = cv2.inRange(roi, np.array(PARKING_HSV_LOW1, dtype=np.uint8),
                          np.array(PARKING_HSV_HIGH1, dtype=np.uint8))
    m2 = cv2.inRange(roi, np.array(PARKING_HSV_LOW2, dtype=np.uint8),
                          np.array(PARKING_HSV_HIGH2, dtype=np.uint8))
    red_mask = cv2.bitwise_or(m1, m2)
    
    cnts, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best_cx = None
    best_area = 0.0
    for c in cnts:
        area = cv2.contourArea(c)
        if area > best_area:
            best_area = area
            M = cv2.moments(c)
            if M['m00'] > 0:
                best_cx = int(M['m10'] / M['m00'])
    
    if best_area < PARKING_MIN_AREA or best_cx is None:
        l, r = controller.compute(error)
        scale = PARKING_SPEED / max(abs(l), abs(r), 1)
        motor.set_speed(*_apply_dir(l * scale, r * scale))
        return
    
    off = best_cx - (WIDTH // 2)
    if abs(off) <= PARKING_CENTER_TOL and best_area > PARKING_MIN_AREA * 4:
        motor.brake()
        _state = 'PARK_TAMAM'
        return
    
    steer = float(off) * 0.3
    l = PARKING_SPEED + steer
    r = PARKING_SPEED - steer
    motor.set_speed(*_apply_dir(l, r))


# ---------------------------------------------------------------------------
# Sürüş döngüsü (ana mantık)
# ---------------------------------------------------------------------------
def drive_loop() -> None:
    global _running, _state, _state_timer, _ovt_phase, _manual_green, _lane_lost_time, _hsv_calib_active, _hsv_calib_roi_list, _hsv_calib_low, _hsv_calib_high
    global _race_start_time, _finish_printed, _time_warning_printed, _no_overtake_until

    frame_count = 0
    last_print = time.time()

    _err_count = 0

    while _running:
      try:
        frame = camera.capture()
        error, debug = lane_detector.process(frame)
        events = event_detector.detect(frame)
        light = events['traffic_light']
        _err_count = 0
        now = time.time()

        # GG/EZ/SPACE/buton ile yeşil ışık simüle
        if _manual_green:
            light = 'green'

        # 240 sn yarış zaman uyarısı (Kural 4.4)
        if (_race_start_time is not None
                and not _time_warning_printed
                and now - _race_start_time > 240.0):
            _time_warning_printed = True
            print("[main] ⚠  240 sn DOLDU — hakem turu sonlandirabilir!")

        # ================================================================
        # Durum makinesi
        # ================================================================
        if _state == 'BEKLIYOR':
            motor.brake()
            if light == 'green':
                _state = 'SURUYOR'
                controller.reset()
                if _race_start_time is None:
                    _race_start_time = now
                print("[main] 🚦 YEŞİL IŞIK ALGILANDI — HAREKET! (Kural 3.4.1)")

        elif _state == 'SURUYOR':
            sign = events.get('sign_type')

            # Tabela tepkileri — yol tespitinden önce kontrol edilir
            if sign == 'cikmazsokak':
                _state = 'CIKMAZSOKAK'
                motor.brake()
                print("[main] 🚫 ÇIKMAZ SOKAK tabelası — araç durdu")
            elif sign == 'sollamabam':
                _no_overtake_until = now + _NO_OVERTAKE_SEC
                print(f"[main] ⛔ SOLLAMA YASAĞI — {_NO_OVERTAKE_SEC:.0f}s geçerli")

            if events['crosswalk']:
                if events['crosswalk_close']:
                    _state = 'YAYA_GECİDİ'
                    _state_timer = now
                    motor.brake()
                else:
                    _state = 'YAYA_YAKLAS'
                    _state_timer = now
            elif events['hemzemin']:
                if events['hemzemin_close']:
                    _state = 'HEMZEMIN'
                    _state_timer = now
                    motor.brake()
                else:
                    _state = 'HEMZEMIN_YAKLAS'
                    _state_timer = now
            elif events['speed_bump']:
                _state = 'TUMSEK'
                _state_timer = now
            elif events['orange_car'] and not events['yellow_car'] and now >= _no_overtake_until:
                _state = 'SOLLAMA'
                _state_timer = now
                _ovt_phase = 0
            elif events['parking_zone']:
                _state = 'PARK'
                controller.reset()
            else:
                # Normal sürüş — şerit kayıp failsafe
                if error is None:
                    if _lane_lost_time is None:
                        _lane_lost_time = now
                        print("[main] ⚠  SERIT KAYIP — sola donus basladi")
                    lost_sec = now - _lane_lost_time
                    if lost_sec < LANE_LOST_TURN_SEC:
                        # Son bilinen dönüş yönünü koru
                        bias = (LANE_LOST_TURN_BIAS
                                if controller.prev_error >= 0
                                else -LANE_LOST_TURN_BIAS)
                        l, r = controller.compute(bias)
                        motor.set_speed(*_apply_dir(l, r))
                    else:
                        # Süre doldu, hâlâ şerit yok → güvenli dur
                        motor.brake()
                else:
                    if _lane_lost_time is not None:
                        print("[main] OK serit tekrar bulundu")
                        _lane_lost_time = None
                        controller.reset()
                    l, r = controller.compute(error)
                    motor.set_speed(*_apply_dir(l, r))

        elif _state == 'YAYA_YAKLAS':
            # Yaya geçidini gördük, henüz 30 cm eşiğine gelmedik — yavaş yaklaş.
            timeout = (now - _state_timer) >= APPROACH_TIMEOUT_SEC
            if events['crosswalk_close'] or timeout:
                _state = 'YAYA_GECİDİ'
                _state_timer = now
                motor.brake()
            elif error is None:
                motor.brake()
            else:
                l, r = controller.compute(error)
                scale = APPROACH_SPEED / max(abs(l), abs(r), 1)
                motor.set_speed(*_apply_dir(l * scale, r * scale))

        elif _state == 'HEMZEMIN_YAKLAS':
            timeout = (now - _state_timer) >= APPROACH_TIMEOUT_SEC
            if events['hemzemin_close'] or timeout:
                _state = 'HEMZEMIN'
                _state_timer = now
                motor.brake()
            elif error is None:
                motor.brake()
            else:
                l, r = controller.compute(error)
                scale = APPROACH_SPEED / max(abs(l), abs(r), 1)
                motor.set_speed(*_apply_dir(l * scale, r * scale))

        elif _state == 'YAYA_GECİDİ':
            motor.brake()
            if now - _state_timer >= CROSSWALK_WAIT_SEC:
                _state = 'SURUYOR'
                controller.reset()

        elif _state == 'HEMZEMIN':
            motor.brake()
            if now - _state_timer >= HEMZEMIN_WAIT_SEC:
                _state = 'SURUYOR'
                controller.reset()

        elif _state == 'TUMSEK':
            l, r = controller.compute(error)
            scale = SPEED_BUMP_SPEED / max(abs(l), abs(r), 1)
            motor.set_speed(*_apply_dir(l * scale, r * scale))
            if now - _state_timer >= SPEED_BUMP_SLOW_SEC:
                _state = 'SURUYOR'

        elif _state == 'SOLLAMA':
            _run_overtaking(error, now)

        elif _state == 'PARK':
            _run_parking(frame, error)

        elif _state == 'CIKMAZSOKAK':
            motor.brake()

        elif _state == 'PARK_TAMAM':
            motor.brake()
            if not _finish_printed:
                _finish_printed = True
                if _race_start_time is not None:
                    elapsed = now - _race_start_time
                    bonus = 240.0 - elapsed
                    print(f"[main] 🏁 BITIRME: {elapsed:.1f}s | "
                          f"Bitirme katsayisi: {bonus:+.0f} (Kural 4.3)")
        
        # ---- Kayıt ----
        logger.update(error)

        # ---- Detayli tani kaydi (DiagLogger) ----
        # Lane detector son frame durumunu (varsa) topla
        ll = getattr(lane_detector, 'last_near_left', None)
        lr = getattr(lane_detector, 'last_near_right', None)
        fl = getattr(lane_detector, 'last_far_left', None)
        fr = getattr(lane_detector, 'last_far_right', None)
        lc = getattr(lane_detector, 'last_lane_center', None)
        mp = getattr(lane_detector, 'last_mask_pct', None)
        vm = getattr(lane_detector, 'last_v_mean', None)
        # Olay flag'lerini kisa stringe cevir
        ev_str = ",".join(
            k for k, v in events.items()
            if v and k not in ('traffic_light', 'sign_type', 'sign_blue')
        )
        diag.log(
            state=_state,
            light=light or "",
            sign=events.get('sign_type') or "",
            error=error,
            lane_center=lc,
            near_left=ll, near_right=lr,
            far_left=fl, far_right=fr,
            mask_white_pct=mp,
            v_mean=vm,
            lost_frames=getattr(controller, 'lost_frames', 0),
            events=ev_str,
        )

        # ---- HSV Kalibrasyon modu aktifse araci durdur ----
        if _hsv_calib_active and _state not in ('BEKLIYOR', 'CIKMAZSOKAK'):
            motor.brake()
        
        # ---- Önizleme penceresi ----
        if SHOW_PREVIEW:
            raw_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            
            # HSV Kalibrasyon modu aktifse
            if _hsv_calib_active:
                # Kalibrasyon penceresi
                cal_display = _draw_hsv_overlay(raw_bgr)
                cv2.imshow('Otonom Arac', cal_display)
                cv2.setMouseCallback('Otonom Arac', _hsv_mouse_callback)
                
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q') or key == 27:  # Q veya Esc = kalibrasyondan cik
                    _hsv_calib_active = False
                    _hsv_calib_roi_list = []
                    _hsv_calib_low = None
                    _hsv_calib_high = None
                    cv2.setMouseCallback('Otonom Arac', lambda *args: None)
                    print("[kalibrasyon] Kalibrasyon modu kapandi, normal surus devam")
                elif key == ord('z'):  # Z = son ROI'yi sil
                    if _hsv_calib_roi_list:
                        _hsv_calib_roi_list.pop()
                        print(f"[kalibrasyon] Son ROI silindi, kalan: {len(_hsv_calib_roi_list)}")
                elif key == ord('r'):  # R = tum ROI'leri temizle
                    _hsv_calib_roi_list = []
                    _hsv_calib_low = None
                    _hsv_calib_high = None
                    print("[kalibrasyon] Tum ROI'ler temizlendi")
                elif key == ord('c'):  # C = hesapla
                    result = _compute_hsv_bounds(frame)
                    if result:
                        _hsv_calib_low, _hsv_calib_high = result
                        print(f"[kalibrasyon] HESAPLANDI:")
                        print(f"   LOW:  {_hsv_calib_low}")
                        print(f"   HIGH: {_hsv_calib_high}")
                    else:
                        print("[kalibrasyon] Yetersiz ornek! ROI ekleyin.")
                elif key == ord('s'):  # S = config.py'ye kaydet
                    if _hsv_calib_low and _hsv_calib_high:
                        try:
                            import re
                            cfg_path = os.path.join(os.path.dirname(__file__), 'config.py')
                            with open(cfg_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                            
                            # USE_MANUAL_HSV guncelle
                            content = re.sub(r'USE_MANUAL_HSV\s*=\s*\w+', 'USE_MANUAL_HSV = True', content)
                            # MANUAL_HSV_LOW guncelle
                            content = re.sub(r'MANUAL_HSV_LOW\s*=\s*\([^)]+\)', f'MANUAL_HSV_LOW = {_hsv_calib_low}', content)
                            # MANUAL_HSV_HIGH guncelle
                            content = re.sub(r'MANUAL_HSV_HIGH\s*=\s*\([^)]+\)', f'MANUAL_HSV_HIGH = {_hsv_calib_high}', content)
                            
                            with open(cfg_path, 'w', encoding='utf-8') as f:
                                f.write(content)
                            print(f"[kalibrasyon] ✓ KAYDEDILDI config.py:")
                            print(f"   USE_MANUAL_HSV = True")
                            print(f"   MANUAL_HSV_LOW = {_hsv_calib_low}")
                            print(f"   MANUAL_HSV_HIGH = {_hsv_calib_high}")
                            print("[kalibrasyon] Yeniden baslatmaniz gerekmez, degerler anlik aktif!")
                        except Exception as e:
                            print(f"[kalibrasyon] Kaydetme hatasi: {e}")
                    else:
                        print("[kalibrasyon] Once C ile hesaplayin!")
            else:
                # Normal onizleme
                cv2.putText(raw_bgr,
                            f"{_state} | {f'{error:+d}px' if error is not None else 'SERIT YOK'}",
                            (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 255), 2)
                debug_bgr = cv2.cvtColor(debug, cv2.COLOR_RGB2BGR)
                debug_bgr = cv2.resize(debug_bgr, (WIDTH, debug_bgr.shape[0]))
                cv2.imshow('Otonom Arac', np.vstack([raw_bgr, debug_bgr]))
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    _running = False

        # ---- Periyodik bilgi (her 2 saniyede bir) ----
        frame_count += 1
        if now - last_print >= 2.0:
            err_str   = f"{error:+d}px" if error is not None else "SERIT_YOK"
            light_str = light or "yok"
            fps       = frame_count / (now - last_print)
            ev_flags  = " ".join(
                k.upper() for k, v in events.items()
                if v and k not in ('traffic_light', 'sign_type', 'sign_blue')
            ) or "-"
            if events.get('sign_type'):
                ev_flags += f" TABELA:{events['sign_type']}"
            t_str = (f"t={now - _race_start_time:.0f}s "
                     if _race_start_time is not None else "")
            print(f"[main] [{_state:14s}] {t_str}err={err_str:8s} | "
                  f"isik={light_str:5s} | olaylar={ev_flags} | FPS={fps:.1f}")
            frame_count = 0
            last_print  = now

      except Exception as _e:
        _err_count += 1
        import traceback
        print(f"[main] KARE HATASI ({_err_count}): {_e}")
        if _err_count == 1:
            traceback.print_exc()
        if _err_count > 30:
            print("[main] Art arda 30+ hata — çıkılıyor.")
            _running = False


# ---------------------------------------------------------------------------
# Kapatma
# ---------------------------------------------------------------------------
def _shutdown(sig=None, frame=None) -> None:
    global _running
    print("\n[main] Kapatılıyor...")
    _running = False
    try:
        motor.stop()
        camera.stop()
        logger.close()
        diag.close()
        if _button_handle is not None:
            try:
                _button_handle.close()
            except Exception:
                pass
        cv2.destroyAllWindows()
    except Exception as e:
        print(f"[main] Kapatma hatası: {e}")
    sys.exit(0)


def _on_button_pressed() -> None:
    """Fiziksel start butonu (Kural 3.4.1, +50 puan): yeşil ışık simülasyonu."""
    global _manual_green
    if not _manual_green:
        print("\n[main] 🔘 BUTON basıldı — YEŞİL IŞIK! 🚦")
        _manual_green = True


def _setup_start_button():
    """gpiozero.Button ile fiziksel start butonu bağla.

    Pi/gpiozero yoksa veya pin meşgulse sessizce skip — kod yine
    klavye/yeşil ışık ile çalışır. Bu sayede buton donanımı hazır
    olmasa bile geliştirme/test sürer.
    """
    global _button_handle
    if not _HAS_BUTTON:
        print("[main] gpiozero yok — fiziksel buton devre dışı (klavye/ışık aktif).")
        return
    try:
        _button_handle = _GpioButton(
            START_BUTTON_PIN, pull_up=True, bounce_time=0.05
        )
        _button_handle.when_pressed = _on_button_pressed
        print(f"[main] ✅ Fiziksel start butonu hazır (GPIO {START_BUTTON_PIN}).")
    except Exception as e:
        _button_handle = None
        print(f"[main] Buton kurulumu basarisiz ({e}) — klavye/ışık ile başlatın.")


signal.signal(signal.SIGINT,  _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


# ---------------------------------------------------------------------------
# Giriş noktası
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    print()
    print("[main] ╔════════════════════════════════════════════╗")
    print("[main] ║   OTONOM ARAÇ — BAŞLAMA MODUNDA            ║")
    print("[main] ╚════════════════════════════════════════════╝")
    print()
    print("[main] BAŞLAMA YÖNTEMI:")
    print("[main]   1️⃣  Trafik ışığı yeşil olur     → Araç otomatik başlar")
    print("[main]   2️⃣  'GG', 'EZ' veya 'EFN' yazın → Araç başlar (test)")
    print("[main]   3️⃣  SPACE (boşluk) tuşu basın   → Araç hemen başlar (kısayol)")
    print(f"[main]   4️⃣  Fiziksel buton (GPIO {START_BUTTON_PIN}) → +50 puan (Kural 3.4.1)")
    print()
    print("[main] DİĞER:")
    print("[main]   C tuşu        → HSV Kalibrasyon modu (surus icinde)")
    print("[main]   Q tuşu        → Programdan çık")
    print("[main]   Ctrl+C        → Acil durdurma")
    print()
    
    # Klavye dinleyiciyi ayrı thread'de başlat
    kb_thread = threading.Thread(target=keyboard_listener, daemon=True)
    kb_thread.start()

    # Fiziksel start butonu (varsa) — bekletmez, donanım yoksa pas geçer
    _setup_start_button()

    print("[main] Kamera, lane detector, event detector hazir.")
    print("[main] Ayar icin: python tune.py")
    print("[main]")
    print("[main] ✅ Sistem hazir - YESIL ISIK BEKLENIYOR...")
    print()
    
    # Ana sürüş döngüsü
    try:
        drive_loop()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        import traceback
        print(f"[main] FATAL HATA: {e}")
        traceback.print_exc()
    finally:
        _shutdown()
