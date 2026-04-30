#!/usr/bin/env python3
# =============================================================================
# pd_tune.py  —  KP / KD interaktif PD kazanç ayarlama aracı
#
# Evde (herhangi bir zemine beyaz bant yapıştırarak) çalıştırılabilir.
# Araç giderken hata logunu canlı ekrana basar; salınım / gecikme görürsün.
#
# Kullanım:
#   python pd_tune.py
#
# Adımlar:
#   1) Başlangıç KP/KD değerlerini gir (config.py'den oku)
#   2) Araç gider, hata grafiği terminale çizilir
#   3) q = dur, değerleri ayarla, tekrar dene
#   4) İyi görünen değerleri config.py'ye yaz
# =============================================================================
import sys
import time
import threading
import collections

try:
    from lane import LaneDetector
    from controller import PDController
    from motor import MotorDriver
except ImportError:
    print("lane.py / controller.py / motor.py bulunamadı. Aynı klasörde çalıştır.")
    sys.exit(1)

try:
    from picamera2 import Picamera2
    _USE_PI = True
except ImportError:
    _USE_PI = False

import cv2
import numpy as np
from config import WIDTH, HEIGHT


# ---------------------------------------------------------------------------
# Kamera
# ---------------------------------------------------------------------------
class _Cam:
    def __init__(self):
        if _USE_PI:
            self._c = Picamera2()
            self._c.configure(self._c.create_preview_configuration(
                main={"size": (WIDTH, HEIGHT), "format": "RGB888"}
            ))
            self._c.start(); time.sleep(1)
        else:
            self._cap = cv2.VideoCapture(0)
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  WIDTH)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)

    def capture(self):
        if _USE_PI:
            return self._c.capture_array()
        ret, f = self._cap.read()
        if not ret:
            return np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        return cv2.cvtColor(cv2.resize(f, (WIDTH, HEIGHT)), cv2.COLOR_BGR2RGB)

    def stop(self):
        if _USE_PI: self._c.stop()
        else: self._cap.release()


# ---------------------------------------------------------------------------
# ASCII hata grafiği (terminal genişliği kadar)
# ---------------------------------------------------------------------------
GRAPH_WIDTH  = 60
GRAPH_HEIGHT = 15
ERROR_SCALE  = 200   # ±200 px = tam grafik yüksekliği

def draw_graph(errors: collections.deque) -> str:
    rows = []
    mid  = GRAPH_HEIGHT // 2
    for row in range(GRAPH_HEIGHT):
        line = []
        for i, e in enumerate(list(errors)[-GRAPH_WIDTH:]):
            # e: -ERROR_SCALE..+ERROR_SCALE → 0..GRAPH_HEIGHT
            mapped = int((e / ERROR_SCALE) * mid) + mid
            mapped = max(0, min(GRAPH_HEIGHT - 1, mapped))
            if row == mid:
                ch = '─' if mapped != mid else '┼'
            elif row == mapped:
                ch = '█'
            else:
                ch = ' '
            line.append(ch)
        rows.append('│' + ''.join(line) + '│')
    rows.insert(0,  f"┌{'─'*GRAPH_WIDTH}┐  hata (px)")
    rows.append(   f"└{'─'*GRAPH_WIDTH}┘  +{ERROR_SCALE}↑  0─── -{ERROR_SCALE}↓")
    return '\n'.join(rows)


# ---------------------------------------------------------------------------
# Ana döngü
# ---------------------------------------------------------------------------
def run_tuning(kp: float, kd: float, duration: float = 10.0):
    cam  = _Cam()
    det  = LaneDetector()
    ctrl = PDController()
    mot  = MotorDriver()

    # ctrl'nin config değerleri yerine test değerlerini kullan
    import controller as ctrl_mod
    ctrl_mod.KP = kp
    ctrl_mod.KD = kd

    errors  = collections.deque(maxlen=GRAPH_WIDTH * 2)
    running = True
    start   = time.time()

    print(f"\nKP={kp}  KD={kd}  |  {duration}s test  |  q=dur")
    print("─" * 50)

    try:
        import tty, termios
        fd  = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        tty.setraw(fd)
        nonblock = True
    except Exception:
        nonblock = False

    def key_listener():
        nonlocal running
        if not nonblock: return
        import select
        while running:
            if select.select([sys.stdin], [], [], 0.1)[0]:
                ch = sys.stdin.read(1)
                if ch in ('q', 'Q'):
                    running = False

    t = threading.Thread(target=key_listener, daemon=True)
    t.start()

    try:
        while running and (time.time() - start) < duration:
            frame = cam.capture()
            error, _ = det.process(frame)
            errors.append(error if error is not None else 0)

            l, r = ctrl.compute(error)
            mot.set_speed(l, r)

            # Terminali temizle ve grafik çiz
            print("\033[H\033[J", end="")
            print(f"KP={kp:.3f}  KD={kd:.3f}  |  "
                  f"hata={errors[-1]:+.0f}px  |  "
                  f"süre={time.time()-start:.1f}s  |  q=dur")
            print(draw_graph(errors))

            stats_arr = list(errors)
            if stats_arr:
                print(f"\nOrtalama: {sum(stats_arr)/len(stats_arr):+.1f}px  |  "
                      f"Maks: {max(abs(e) for e in stats_arr):.0f}px  |  "
                      f"Std: {(sum((e - sum(stats_arr)/len(stats_arr))**2 for e in stats_arr)/len(stats_arr))**0.5:.1f}px")

    finally:
        mot.brake()
        time.sleep(0.3)
        mot.stop()
        cam.stop()
        if nonblock:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    # Özet
    if errors:
        ea = list(errors)
        mean = sum(ea) / len(ea)
        std  = (sum((e-mean)**2 for e in ea) / len(ea)) ** 0.5
        print(f"\n{'='*50}")
        print(f"SONUÇ  KP={kp}  KD={kd}")
        print(f"  Ortalama hata : {mean:+.1f} px  (0'a yakın = iyi)")
        print(f"  Std sapma     : {std:.1f} px   (düşük = stabil)")
        print(f"  Tavsiye:")
        if std > 30:
            print("  ⚠️  Yüksek salınım → KP'yi azalt veya KD'yi artır")
        elif std > 15:
            print("  ⚠️  Orta salınım → KD'yi biraz artır")
        else:
            print("  ✅  Stabil görünüyor!")
        if abs(mean) > 20:
            print(f"  ⚠️  Kalıcı sapma ({mean:+.0f}px) → LEFT_TRIM/RIGHT_TRIM kontrol et")


# ---------------------------------------------------------------------------
# Giriş noktası
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import config as cfg
    print("PD Kazanç Ayarlama Aracı")
    print(f"Mevcut değerler: KP={cfg.KP}  KD={cfg.KD}\n")

    try:
        kp_in = input(f"Yeni KP [{cfg.KP}]: ").strip()
        kd_in = input(f"Yeni KD [{cfg.KD}]: ").strip()
        dur_in = input("Test süresi (saniye) [10]: ").strip()

        kp  = float(kp_in)  if kp_in  else cfg.KP
        kd  = float(kd_in)  if kd_in  else cfg.KD
        dur = float(dur_in) if dur_in else 10.0

        run_tuning(kp, kd, dur)

        print(f"\n📋 config.py'ye yaz:")
        print(f"   KP = {kp}")
        print(f"   KD = {kd}")

    except KeyboardInterrupt:
        print("\nKesintiye uğradı.")
    except ValueError:
        print("Geçersiz sayı girişi.")
