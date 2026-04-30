#!/usr/bin/env python3
"""
simple_lane.py — BASIT VE ROBUST serit takip (2 gun kaldi versiyonu)

Ozgul yaklasimlar (karmasik):
- 3 ROI, polinom fit, lookahead, HSV kalibrasyon vs

Bu dosya (basit, robust):
- Otsu otomatik threshold (HSV kalibrasyona gerek yok)
- Center of Mass (agirlikli ortalama)
- Tek ROI (alt yari)
- Ters steering destegi (INVERT_STEERING flagi)

Kullanim:
  from simple_lane import SimpleLaneDetector
  detector = SimpleLaneDetector()
  error, debug = detector.process(frame)
"""
import cv2
import numpy as np

from config import WIDTH, HEIGHT

# EGER ARAC SOLA SAPIYORSA BUNU TRUE YAP (ters donus)
INVERT_STEERING = False

# Gorsel ayarlar
ROI_TOP = 0.5  # Goruntunun ust yarisini at (perspektif icin)


class SimpleLaneDetector:
    """
    Basit serit dedektoru — Otsu threshold + Center of Mass.
    
    Hata > 0: Serit merkezi sagda (sola don)
    Hata < 0: Serit merkezi solda (saga don)
    (Eger INVERT_STEERING = True ise tersi)
    """
    
    def __init__(self, invert_steering=INVERT_STEERING):
        self.invert = invert_steering
        self.roi_top = int(HEIGHT * ROI_TOP)
        self.mid_x = WIDTH // 2
        
    def process(self, frame_rgb: np.ndarray) -> tuple:
        """
        Args:
            frame_rgb: RGB kare (H, W, 3)
        
        Returns:
            error: int, piksel olarak serit merkezi ofseti (None = bulunamadi)
            debug: BGR debug gorseli
        """
        h, w = frame_rgb.shape[:2]
        
        # ROI kirp (alt yari)
        roi = frame_rgb[self.roi_top:, :]
        
        # Gri cevir ve yumusat
        gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Otsu otomatik threshold — HSV kalibrasyonuna gerek yok!
        _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Gurisleri temizle (morfoloji)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        
        # Center of Mass hesapla (agirlikli ortalama)
        moments = cv2.moments(binary)
        
        if moments['m00'] > 1000:  # Yeterli beyaz piksel varsa
            cx = int(moments['m10'] / moments['m00'])
            cy = int(moments['m01'] / moments['m00'])
            
            # Global koordinatlara cevir
            global_cx = cx
            global_cy = self.roi_top + cy
            
            # Hata = serit merkezi - goruntu merkezi
            error = global_cx - self.mid_x
            
            if self.invert:
                error = -error
                
        else:
            error = None
            global_cx = None
            global_cy = None
        
        # Debug gorseli olustur
        debug = self._draw_debug(frame_rgb, binary, global_cx, global_cy, error)
        
        return error, debug
    
    def _draw_debug(self, frame_rgb, binary_roi, cx, cy, error):
        """Debug gorseli."""
        # Ana goruntuyu BGR cevir
        debug = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        
        # ROI cizgisi
        cv2.line(debug, (0, self.roi_top), (WIDTH, self.roi_top), (255, 0, 0), 2)
        
        # Binary ROI'yi tam boyuta cevir ve yanina koy
        binary_full = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
        binary_full[self.roi_top:, :] = binary_roi
        binary_color = cv2.cvtColor(binary_full, cv2.COLOR_GRAY2BGR)
        
        # Yan yana birlestir
        combined = np.hstack([debug, binary_color])
        
        # Merkez cizgisi
        cv2.line(combined, (WIDTH//2, 0), (WIDTH//2, HEIGHT), (0, 255, 255), 1)
        cv2.line(combined, (WIDTH + WIDTH//2, 0), (WIDTH + WIDTH//2, HEIGHT), (0, 255, 255), 1)
        
        # Tespit noktasi
        if cx is not None:
            cv2.circle(combined, (cx, cy), 8, (0, 0, 255), -1)
            cv2.circle(combined, (WIDTH + cx, cy), 8, (0, 0, 255), -1)
        
        # Bilgi metni
        err_str = f"ERR:{error:+4d}" if error is not None else "ERR:YOK"
        inv_str = " (TERS)" if self.invert else ""
        cv2.putText(combined, f"{err_str}{inv_str}", (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(combined, "Otsu + Center of Mass", (10, HEIGHT - 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        
        return combined


# Test
if __name__ == "__main__":
    print("SimpleLaneDetector test — kamera baslatiliyor...")
    
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
    
    detector = SimpleLaneDetector(invert_steering=False)
    
    print("Q: Cik | I: Invert steering toggle")
    
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
        cv2.imshow("Simple Lane Detector", debug)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('i'):
            detector.invert = not detector.invert
            print(f"[test] Invert steering: {detector.invert}")
    
    if _use_pi:
        cam.stop()
    else:
        cam.release()
    cv2.destroyAllWindows()
