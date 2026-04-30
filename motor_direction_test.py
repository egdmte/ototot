#!/usr/bin/env python3
"""
motor_direction_test.py — Motor yön kalibrasyonu

Bu test, controller→motor zinciri ile gerçek araba hareketi
arasında uyum olup olmadığını kontrol eder.

Kullanim:
    python motor_direction_test.py

Tuslar:
    F : ILERI    (her iki tekerlek pozitif)
    B : GERI     (her iki tekerlek negatif)
    L : SOLA DON (controller ile, error=+100)
    R : SAGA DON (controller ile, error=-100)
    1 : SOL TEKERLEK ileri, sag dur
    2 : SAG TEKERLEK ileri, sol dur
    SPACE: dur
    Q : cik

ONEMLI: Arabayi sira ustune koyun ki tekerlekler havadasin.
        Sonra her tusu bas ve OZGUN olarak hangi tekerlegin dondugunu
        ve hangi yone gittigini not et.
"""
import time
import sys

import numpy as np

from motor import MotorDriver
from controller import PDController


def main():
    print(__doc__)
    print()
    print("Hazir misin? Tekerlekler havada olmali. ENTER ile baslat...")
    input()

    motor = MotorDriver()
    pid   = PDController()

    try:
        # OpenCV pencere ile keyboard input
        import cv2
        img = np.zeros((300, 600, 3), dtype=np.uint8)
        cv2.imshow("Motor Test - F/B/L/R/1/2/SPACE/Q", img)

        while True:
            cv2.imshow("Motor Test - F/B/L/R/1/2/SPACE/Q", img)
            k = cv2.waitKey(50) & 0xFF

            if k == ord('q') or k == 27:
                break
            elif k == ord('f'):
                print("\n[F] ILERI: left=+50, right=+50")
                print("    Beklenen: ARABA DUZ ILERI gidiyor")
                motor.set_speed(50, 50)
            elif k == ord('b'):
                print("\n[B] GERI: left=-50, right=-50")
                print("    Beklenen: ARABA DUZ GERI gidiyor")
                motor.set_speed(-50, -50)
            elif k == ord('l'):
                print("\n[L] SOLA DON: controller.compute(error=+100)")
                pid.reset()
                left, right = pid.compute(100)
                print(f"    controller -> left={left:.1f}, right={right:.1f}")
                print("    Beklenen: ARABA SOLA donuyor")
                motor.set_speed(left, right)
            elif k == ord('r'):
                print("\n[R] SAGA DON: controller.compute(error=-100)")
                pid.reset()
                left, right = pid.compute(-100)
                print(f"    controller -> left={left:.1f}, right={right:.1f}")
                print("    Beklenen: ARABA SAGA donuyor")
                motor.set_speed(left, right)
            elif k == ord('1'):
                print("\n[1] SOL motor pin: 60, sag motor pin: 0")
                print("    SOL etiketli motor pinine baglı olan tekerlek donmeli")
                motor.set_speed(60, 0)
            elif k == ord('2'):
                print("\n[2] SOL motor pin: 0, sag motor pin: 60")
                print("    SAG etiketli motor pinine baglı olan tekerlek donmeli")
                motor.set_speed(0, 60)
            elif k == ord(' '):
                print("\n[SPACE] DUR")
                motor.set_speed(0, 0)
                motor.brake()

    finally:
        print("\n[motor_test] kapatiliyor")
        motor.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
