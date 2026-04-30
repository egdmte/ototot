#!/usr/bin/env python3
"""
quick_calibrate.py — ACIL motor trim + HSV kalibrasyonu (2 gün kaldı versiyonu)

1. Duz gitme testi (W/S ile ileri/geri, A/D ile trim ayari)
2. Otsu HSV kalibrasyonu (otomatik beyaz tespit)
"""
import cv2
import numpy as np
import os
import sys
import time
import termios
import tty

try:
    from picamera2 import Picamera2
    _USE_PICAMERA = True
except ImportError:
    _USE_PICAMERA = False
    print("[quick] picamera2 yok — OpenCV kullanılıyor")

# Config'den temel degerler
sys.path.insert(0, os.path.dirname(__file__))
from config import WIDTH, HEIGHT, CAMERA_BGR_OUTPUT, CAMERA_ROTATE_180

# Global trim degerleri (buradan config.py'ye yazilacak)
left_trim = 1.0
right_trim = 1.0


class SimpleCamera:
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
            self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
            self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    
    def capture(self):
        if _USE_PICAMERA:
            f = self.cam.capture_array()
            if f.ndim == 3 and f.shape[2] == 4:
                f = f[:, :, :3]
            if CAMERA_BGR_OUTPUT:
                f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
            if CAMERA_ROTATE_180:
                f = cv2.rotate(f, cv2.ROTATE_180)
            return f
        ret, f = self.cam.read()
        if not ret:
            return np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
        if CAMERA_ROTATE_180:
            f = cv2.rotate(f, cv2.ROTATE_180)
        return f
    
    def close(self):
        if _USE_PICAMERA:
            self.cam.stop()
        else:
            self.cam.release()


def otsu_hsv_calibrate(frame_rgb):
    """Otomatik Otsu threshold ile beyaz serit HSV araligi bul."""
    hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
    v_channel = hsv[:, :, 2]
    
    # Otsu otomatik threshold
    blur = cv2.GaussianBlur(v_channel, (5, 5), 0)
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Beyaz piksellerin HSV degerlerini topla
    white_mask = binary > 0
    if np.sum(white_mask) < 100:
        return None, None, binary
    
    white_pixels = hsv[white_mask]
    
    # Persentil ile guvenli aralik
    h_low, h_high = 0, 180  # H genelde full range
    s_low, s_high = np.percentile(white_pixels[:, 1], [1, 99])
    v_low, v_high = np.percentile(white_pixels[:, 2], [1, 99])
    
    # Margin ekle
    s_low = max(0, s_low - 20)
    s_high = min(255, s_high + 20)
    v_low = max(0, v_low - 30)
    v_high = min(255, v_high + 10)  # ust sinir asiri parlakliklari at
    
    low = (int(h_low), int(s_low), int(v_low))
    high = (int(h_high), int(s_high), int(v_high))
    
    return low, high, binary


def motor_trim_test():
    """Duz gitme testi — klavye trim ayari."""
    global left_trim, right_trim
    
    print("\n" + "="*50)
    print("MOTOR TRIM KALIBRASYONU")
    print("="*50)
    print("W/S: Ileri/Geri")
    print("A: Sol trim dusur (sola donuyorsa)")  
    print("D: Sag trim dusur (saga donuyorsa)")
    print("Q: Cik ve kaydet")
    print("="*50 + "\n")
    
    # GPIO varsa motorlari baslat (yoksa simulasyon)
    try:
        from motor import MotorDriver
        motor = MotorDriver()
        has_motor = True
    except:
        print("[quick] Motor yok — simulasyon modu")
        motor = None
        has_motor = False
    
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    
    speed = 0
    
    try:
        while True:
            ch = sys.stdin.read(1)
            
            if ch == 'q' or ch == 'Q':
                break
            elif ch == 'w' or ch == 'W':
                speed = 50  # %50 hizla test
            elif ch == 's' or ch == 'S':
                speed = -30
            elif ch == ' ':
                speed = 0
            elif ch == 'a' or ch == 'A':
                left_trim -= 0.05  # Solu yavaslat (sola donuyorsa)
                print(f"[trim] LEFT={left_trim:.2f}, RIGHT={right_trim:.2f}")
            elif ch == 'd' or ch == 'D':
                right_trim -= 0.05  # Sagi yavaslat (saga donuyorsa)
                print(f"[trim] LEFT={left_trim:.2f}, RIGHT={right_trim:.2f}")
            
            if has_motor and motor:
                motor.set_speed(speed * left_trim, speed * right_trim)
                
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        if has_motor and motor:
            motor.set_speed(0, 0)
    
    return left_trim, right_trim


def hsv_auto_calibrate():
    """Kameradan Otsu ile HSV kalibrasyon."""
    print("\n" + "="*50)
    print("OTOMATIK HSV KALIBRASYONU (Otsu)")
    print("="*50)
    print("Araci seridin uzerine gotur")
    print("SPACE: Kare al ve hesapla")
    print("S: Kaydet ve cik")
    print("Q: Cik (kaydetmeden)")
    print("="*50 + "\n")
    
    cam = SimpleCamera()
    best_low = None
    best_high = None
    
    try:
        while True:
            frame = cam.capture()
            low, high, binary = otsu_hsv_calibrate(frame)
            
            # Goster
            disp = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            if low and high:
                cv2.putText(disp, f"LOW:{low}", (10, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                cv2.putText(disp, f"HIGH:{high}", (10, 55),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
            cv2.imshow("Orijinal", disp)
            cv2.imshow("Otsu Maske", binary)
            
            key = cv2.waitKey(30) & 0xFF
            if key == ord('q'):
                break
            elif key == ord(' ') and low and high:
                best_low, best_high = low, high
                print(f"[otsu] Alindi: LOW={low}, HIGH={high}")
            elif key == ord('s') and best_low and best_high:
                # Config.py'ye yaz
                cfg_path = os.path.join(os.path.dirname(__file__), 'config.py')
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                import re
                content = re.sub(r'USE_MANUAL_HSV\s*=\s*\w+', 'USE_MANUAL_HSV = True', content)
                content = re.sub(r'MANUAL_HSV_LOW\s*=\s*\([^)]+\)', f'MANUAL_HSV_LOW = {best_low}', content)
                content = re.sub(r'MANUAL_HSV_HIGH\s*=\s*\([^)]+\)', f'MANUAL_HSV_HIGH = {best_high}', content)
                
                with open(cfg_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                print(f"[otsu] ✓ KAYDEDILDI config.py")
                print(f"       MANUAL_HSV_LOW = {best_low}")
                print(f"       MANUAL_HSV_HIGH = {best_high}")
                break
                
    finally:
        cam.close()
        cv2.destroyAllWindows()


def main():
    print("\n" + "="*50)
    print("ACIL KALIBRASYON ARACI (2 gun versiyonu)")
    print("="*50)
    print("1: Motor trim kalibrasyonu (duz gitme)")
    print("2: Otomatik HSV kalibrasyonu (Otsu)")
    print("q: Cik")
    print("="*50)
    
    while True:
        choice = input("\nSecim (1/2/q): ").strip().lower()
        
        if choice == 'q':
            break
        elif choice == '1':
            left, right = motor_trim_test()
            
            # Config.py'ye yaz
            cfg_path = os.path.join(os.path.dirname(__file__), 'config.py')
            with open(cfg_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            import re
            # Trim degerlerini guncelle (LOW ve HIGH ayni yap)
            content = re.sub(r'LEFT_TRIM_LOW\s*=\s*[\d.]+', f'LEFT_TRIM_LOW = {left:.2f}', content)
            content = re.sub(r'LEFT_TRIM_HIGH\s*=\s*[\d.]+', f'LEFT_TRIM_HIGH = {left:.2f}', content)
            content = re.sub(r'RIGHT_TRIM_LOW\s*=\s*[\d.]+', f'RIGHT_TRIM_LOW = {right:.2f}', content)
            content = re.sub(r'RIGHT_TRIM_HIGH\s*=\s*[\d.]+', f'RIGHT_TRIM_HIGH = {right:.2f}', content)
            
            with open(cfg_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"\n[trim] ✓ Kaydedildi: LEFT={left:.2f}, RIGHT={right:.2f}")
            print("[trim] Artik araba duz gitmeli!")
            
        elif choice == '2':
            hsv_auto_calibrate()
            
    print("\n[quick] Bay!")


if __name__ == "__main__":
    main()
