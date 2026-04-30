#!/usr/bin/env python3
"""
lane_center.py — IKI BEYAZ SERIT ARASINDAKI SIYAH YOLU TAKIP EDER

Klasik lane detection'un tersi:
- Eski: Beyaz piksellerin agirlik merkezi (ortada tek serit varsa sapar)
- Bu: Sol beyaz serit + Sag beyaz serit bul, ortalarinin ortasina git

360 donme sebebi: Tek serit gorunce o seride dogru gidiyor, digerini bulamayinca
ters yone donuyor. Bu dosya IKI serit arasini hedefler.
"""
import cv2
import numpy as np

from config import WIDTH, HEIGHT, USE_MANUAL_HSV, MANUAL_HSV_LOW, MANUAL_HSV_HIGH

# Fallback HSV (beyaz serit)
WHITE_LOW = np.array([0, 0, 180]) if not USE_MANUAL_HSV else np.array(MANUAL_HSV_LOW)
WHITE_HIGH = np.array([180, 50, 255]) if not USE_MANUAL_HSV else np.array(MANUAL_HSV_HIGH)

# ROI — Alt yarisi kullan (yakindaki seritler daha guvenilir)
ROI_TOP_RATIO = 0.4

# Serit arama parametreleri
LANE_MIN_WIDTH = 80      # Minimum serit genisligi (piksel)
LANE_MAX_WIDTH = 400     # Maximum serit genisligi
PEAK_MIN_HEIGHT = 50     # Histogram tepe noktasi minimum yukseklik


class LaneCenterDetector:
    """
    Iki beyaz serit arasindaki SIYAH yolun merkezini bulur.
    
    Hata > 0: Siyah yol merkezi sagda (sola don)
    Hata < 0: Siyah yol merkezi solda (saga don)
    """
    
    def __init__(self, invert_steering=False):
        self.invert = invert_steering
        self.roi_top = int(HEIGHT * ROI_TOP_RATIO)
        self.prev_left = None   # Onceki sol serit konumu (x)
        self.prev_right = None  # Onceki sag serit konumu (x)
        
    def process(self, frame_rgb: np.ndarray) -> tuple:
        """
        Returns:
            error: int, lane center offset from image center (None = no lane)
            debug: BGR debug image showing left/right lines and lane center
        """
        h, w = frame_rgb.shape[:2]
        roi = frame_rgb[self.roi_top:, :]
        
        # Beyaz maske
        hsv = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV)
        white_mask = cv2.inRange(hsv, WHITE_LOW, WHITE_HIGH)
        
        # Histogram — alt kisim (yakindaki seritler)
        hist = np.sum(white_mask[white_mask.shape[0]//2:, :], axis=0)
        
        # Iki tepe noktasi bul (sol ve sag serit)
        left_peak, right_peak = self._find_two_peaks(hist)
        
        # Hafiza kullan (serit kaybolursa son bilinen konumdan ara)
        if left_peak is not None:
            self.prev_left = left_peak
        else:
            left_peak = self.prev_left
            
        if right_peak is not None:
            self.prev_right = right_peak
        else:
            right_peak = self.prev_right
        
        # Iki serit de varsa lane center hesapla
        if left_peak is not None and right_peak is not None:
            lane_center = (left_peak + right_peak) // 2
            lane_width = right_peak - left_peak
            
            # Gecerli serit genisligi kontrolu
            if LANE_MIN_WIDTH < lane_width < LANE_MAX_WIDTH:
                error = lane_center - (w // 2)
                if self.invert:
                    error = -error
                valid = True
            else:
                # Tek serit gorunuyor — digerini tahmin et
                if left_peak is not None and self.prev_right:
                    lane_center = (left_peak + self.prev_right) // 2
                elif right_peak is not None and self.prev_left:
                    lane_center = (self.prev_left + right_peak) // 2
                else:
                    lane_center = w // 2
                error = lane_center - (w // 2)
                if self.invert:
                    error = -error
                valid = True
        elif left_peak is not None:
            # Sadece sol serit gorunuyor — sagdan tahmini lane center
            assumed_right = min(w - 20, left_peak + 200)  # Tahmini serit genisligi
            lane_center = (left_peak + assumed_right) // 2
            error = lane_center - (w // 2)
            if self.invert:
                error = -error
            right_peak = assumed_right
            valid = True
        elif right_peak is not None:
            # Sadece sag serit gorunuyor — soldan tahmini lane center
            assumed_left = max(20, right_peak - 200)
            lane_center = (assumed_left + right_peak) // 2
            error = lane_center - (w // 2)
            if self.invert:
                error = -error
            left_peak = assumed_left
            valid = True
        else:
            error = None
            lane_center = None
            left_peak = None
            right_peak = None
            valid = False
        
        # Debug gorseli
        debug = self._draw_debug(frame_rgb, white_mask, left_peak, right_peak, 
                                  lane_center, error, valid)
        
        return error, debug
    
    def _find_two_peaks(self, hist):
        """Histogramdan iki tepe noktasi (sol ve sag serit) bul."""
        mid = len(hist) // 2
        
        # Sol yarida max
        left_hist = hist[:mid]
        left_peak = np.argmax(left_hist) if np.max(left_hist) > PEAK_MIN_HEIGHT else None
        
        # Sag yarida max
        right_hist = hist[mid:]
        right_peak = np.argmax(right_hist) + mid if np.max(right_hist) > PEAK_MIN_HEIGHT else None
        
        # Aykiri degerleri temizle (cok yakin tepeler tek serittir)
        if left_peak is not None and right_peak is not None:
            if right_peak - left_peak < LANE_MIN_WIDTH:
                # Tek serit — hangisi daha yuksek?
                if hist[left_peak] > hist[right_peak]:
                    right_peak = None
                else:
                    left_peak = None
        
        return left_peak, right_peak
    
    def _draw_debug(self, frame_rgb, mask, left_x, right_x, center_x, error, valid):
        """Debug gorseli ciz."""
        h, w = frame_rgb.shape[:2]
        
        # Ana goruntu
        debug = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        
        # ROI bolgesi
        cv2.line(debug, (0, self.roi_top), (w, self.roi_top), (255, 0, 0), 2)
        
        # Maske kucuk preview
        mask_color = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        mask_resized = cv2.resize(mask_color, (w//3, h//3))
        debug[h//3*2:h, :w//3] = mask_resized
        
        # Serit cizgileri
        if left_x is not None:
            cv2.line(debug, (left_x, self.roi_top), (left_x, h), (0, 255, 0), 3)
            cv2.circle(debug, (left_x, h-50), 8, (0, 255, 0), -1)
        if right_x is not None:
            cv2.line(debug, (right_x, self.roi_top), (right_x, h), (0, 255, 0), 3)
            cv2.circle(debug, (right_x, h-50), 8, (0, 255, 0), -1)
        
        # Lane center (hedef)
        if center_x is not None:
            cv2.line(debug, (center_x, self.roi_top), (center_x, h), (0, 255, 255), 2)
            cv2.circle(debug, (center_x, h-50), 10, (0, 255, 255), -1)
        
        # Goruntu merkezi (referans)
        mid_x = w // 2
        cv2.line(debug, (mid_x, self.roi_top), (mid_x, h), (128, 128, 128), 1)
        
        # Bilgi metni
        status = "LANE OK" if valid else "NO LANE"
        err_str = f"ERR:{error:+4d}" if error is not None else "ERR:NONE"
        
        cv2.putText(debug, f"{status} | {err_str}", (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0) if valid else (0, 0, 255), 2)
        
        if left_x is not None and right_x is not None:
            width = right_x - left_x
            cv2.putText(debug, f"W:{width}px", (10, 60),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
        
        cv2.putText(debug, "SIYAH YOL ORTASI", (10, h-10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        
        return debug


# Test
if __name__ == "__main__":
    print("LaneCenterDetector test — IKI BEYAZ SERIT ARASI...")
    
    try:
        from picamera2 import Picamera2
        cam = Picamera2()
        cam.configure(cam.create_preview_configuration(
            main={"size": (WIDTH, HEIGHT), "format": "RGB888"}
        ))
        cam.start()
        _use_pi = True
    except:
        cam = cv2.VideoCapture(0)
        cam.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        cam.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        _use_pi = False
    
    detector = LaneCenterDetector(invert_steering=False)
    
    print("Q: Cik | I: Invert toggle")
    print("Gorunen: Yesil cizgiler = beyaz seritler, Sari daire = hedef (ortalarin ortasi)")
    
    while True:
        if _use_pi:
            frame = cam.capture_array()
            if frame.ndim == 3 and frame.shape[2] == 4:
                frame = frame[:, :, :3]
        else:
            ret, frame = cam.read()
            if not ret:
                break
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        error, debug = detector.process(frame)
        cv2.imshow("Lane Center (SIYAH YOL)", debug)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('i'):
            detector.invert = not detector.invert
            print(f"[test] Invert: {detector.invert}")
    
    if _use_pi:
        cam.stop()
    else:
        cam.release()
    cv2.destroyAllWindows()
