# =============================================================================
# camera.py  —  Ayar / tanılama için canlı kamera görüntüleyici
#
# Gösterir:
#   - İmleç altındaki pikselin HSV değeri
#   - İkili beyaz-şerit eşik katmanı ('t' ile aç/kapat)
#   - Kuş bakışı perspektif eğriltmesi ('b' ile aç/kapat)
#
# 'q' → çık
# =============================================================================
import time

import cv2
import numpy as np
from picamera2 import Picamera2

from config import WIDTH, HEIGHT
from lane import LaneDetector


def main():
    picam2 = Picamera2()
    cfg = picam2.create_preview_configuration(
        main={"size": (WIDTH, HEIGHT), "format": "RGB888"}
    )
    picam2.configure(cfg)
    picam2.start()
    time.sleep(2)

    detector = LaneDetector()
    cursor   = {"x": WIDTH // 2, "y": HEIGHT // 2}

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_MOUSEMOVE:
            cursor["x"], cursor["y"] = x, y

    cv2.namedWindow("Kamera")
    cv2.setMouseCallback("Kamera", on_mouse)

    show_thresh = False
    show_bird   = False

    print("Kontroller: 't' = eşik | 'b' = kuş bakışı | 'q' = çık")

    try:
        while True:
            frame_rgb = picam2.capture_array()
            frame     = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

            # HSV bilgisi
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            cx, cy = cursor["x"], cursor["y"]
            h, s, v = hsv[cy, cx]
            cv2.putText(
                frame,
                f"HSV ({cx},{cy}): H={h} S={s} V={v}",
                (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 230, 230), 2,
            )
            cv2.circle(frame, (cx, cy), 5, (0, 0, 255), -1)

            if show_bird or show_thresh:
                _, debug_rgb = detector.process(frame_rgb)
                display = cv2.cvtColor(debug_rgb, cv2.COLOR_RGB2BGR)
            else:
                display = frame

            cv2.imshow("Kamera", display)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('t'):
                show_thresh = not show_thresh
                show_bird   = False
            elif key == ord('b'):
                show_bird   = not show_bird
                show_thresh = False

    except Exception as exc:
        print(f"[camera.py] HATA: {exc}")
    finally:
        picam2.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()