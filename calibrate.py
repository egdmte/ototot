# =============================================================================
# calibrate.py  —  Perspektif eğriltme interaktif kalibrasyon aracı
#                  (Raspberry Pi / Picamera2 sürümü)
#
# Dört yeşil tutacağı kamera görüntüsündeki yol trapezoidinin köşelerine sürükle.
# ENTER'a bas → config.py'ye yapıştırmaya hazır PERSP_SRC değerlerini yazdırır.
# 'q' → kaydetmeden çık.
#
# Nokta sırası:  sol-üst, sağ-üst, sol-alt, sağ-alt
# =============================================================================
import cv2
import numpy as np
from config import WIDTH, HEIGHT, PERSP_SRC

try:
    from picamera2 import Picamera2
    _USE_PI = True
except ImportError:
    _USE_PI = False

POINT_RADIUS   = 8
POINT_COLOR    = (0, 255, 0)
SELECTED_COLOR = (0, 0, 255)
LINE_COLOR     = (255, 200, 0)


def draw_overlay(frame: np.ndarray, pts: list, selected: int) -> np.ndarray:
    vis   = frame.copy()
    order = [0, 1, 3, 2, 0]   # kapalı dörtgen çiz
    for i in range(len(order) - 1):
        p1 = tuple(pts[order[i]])
        p2 = tuple(pts[order[i + 1]])
        cv2.line(vis, p1, p2, LINE_COLOR, 1)
    for i, (x, y) in enumerate(pts):
        color = SELECTED_COLOR if i == selected else POINT_COLOR
        cv2.circle(vis, (x, y), POINT_RADIUS, color, -1)
        cv2.putText(vis, str(i), (x + 10, y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    cv2.putText(vis, "Noktaları sürükle | ENTER=kaydet | q=çık",
                (8, HEIGHT - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    return vis


def main():
    # Kamera başlat (Pi veya USB)
    if _USE_PI:
        import time
        picam2 = Picamera2()
        cfg = picam2.create_preview_configuration(
            main={"format": "RGB888", "size": (WIDTH, HEIGHT)}
        )
        picam2.configure(cfg)
        picam2.start()
        time.sleep(1)
        def _get_frame():
            f = picam2.capture_array()
            return cv2.cvtColor(f, cv2.COLOR_RGB2BGR)
        def _stop(): picam2.stop()
    else:
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        def _get_frame():
            ret, f = cap.read()
            return f if ret else np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        def _stop(): cap.release()

    pts      = [list(p) for p in PERSP_SRC]
    selected = -1
    dragging = False

    def on_mouse(event, x, y, flags, param):
        nonlocal selected, dragging
        if event == cv2.EVENT_LBUTTONDOWN:
            dists = [abs(x - p[0]) + abs(y - p[1]) for p in pts]
            idx   = int(np.argmin(dists))
            if dists[idx] < POINT_RADIUS * 3:
                selected = idx
                dragging = True
        elif event == cv2.EVENT_MOUSEMOVE and dragging:
            pts[selected] = [np.clip(x, 0, WIDTH - 1), np.clip(y, 0, HEIGHT - 1)]
        elif event == cv2.EVENT_LBUTTONUP:
            dragging = False

    cam_label = "Pi Camera" if _USE_PI else "USB Camera"
    cv2.namedWindow(f"Kalibrasyon ({cam_label})")
    cv2.setMouseCallback(f"Kalibrasyon ({cam_label})", on_mouse)

    print(f"Kamera: {cam_label}")
    print("Dört köşe tutacağını şerit sınırlarına sürükleyin.")
    print("Nokta sırası:  0=sol-üst  1=sağ-üst  2=sol-alt  3=sağ-alt")
    print("ENTER = kaydet, 'q' = kaydetmeden çık.")

    try:
        while True:
            frame = _get_frame()
            if frame.shape[1] != WIDTH or frame.shape[0] != HEIGHT:
                frame = cv2.resize(frame, (WIDTH, HEIGHT))

            vis = draw_overlay(frame, pts, selected if dragging else -1)
            cv2.imshow(f"Kalibrasyon ({cam_label})", vis)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                print("Kalibrasyon iptal edildi.")
                break
            elif key in (13, 10):   # ENTER
                print("\n# Bunu config.py'ye yapıştır:")
                print(f"PERSP_SRC = {pts}")
                break
    finally:
        _stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()