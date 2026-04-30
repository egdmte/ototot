# =============================================================================
# camtester.py  —  İnteraktif motor ve tahrik testi (kamera gerekmez)
#
# Doğrudan çalıştır:  python camtester.py
# Tuşlar:  w=ileri  s=geri  a=sol dön  d=sağ dön
#          BOŞLUK=dur  q=çık
# Çalıştırmadan önce TEST_SPEED'i güvenli bir değere ayarlayın.
# =============================================================================
try:
    from gpiozero import DigitalOutputDevice, PWMOutputDevice
    _HAS_GPIO = True
except ImportError:
    _HAS_GPIO = False
    print("[camtester] gpiozero bulunamadı — simülasyon modunda")

    class DigitalOutputDevice:
        def __init__(self, pin): pass
        def on(self): pass
        def off(self): pass

    class PWMOutputDevice:
        def __init__(self, pin): self.value = 0.0

from time import sleep
import sys

from config import (
    RIGHT_IN1, RIGHT_IN2, LEFT_IN1, LEFT_IN2,
    LEFT_PWM_PIN, RIGHT_PWM_PIN,
)

TEST_SPEED = 0.5    # 0.0 – 1.0
TURN_SPEED = 0.45

# --- Pin kurulumu (config.py ile eşleşir) --------------------------------
right_in1 = DigitalOutputDevice(RIGHT_IN1)
right_in2 = DigitalOutputDevice(RIGHT_IN2)
left_in1  = DigitalOutputDevice(LEFT_IN1)
left_in2  = DigitalOutputDevice(LEFT_IN2)
right_pwm = PWMOutputDevice(RIGHT_PWM_PIN)
left_pwm  = PWMOutputDevice(LEFT_PWM_PIN)


# --- Temel hareketler -----------------------------------------------------
def stop():
    right_pwm.value = 0
    left_pwm.value  = 0
    for p in (right_in1, right_in2, left_in1, left_in2):
        p.off()


def forward(speed=TEST_SPEED):
    # ⚠️ MOTOR YÖNÜ TERS ÇEVRİLDİ: Sağ motoru geri, sol motoru geri yap (tüm araç geri gider)
    # Hata: burada hızlı düzeltme için...
    # Aslında forward mantığında motor yönü ters olduğu için:
    right_in1.off();  right_in2.on();  right_pwm.value = speed
    left_in1.off();   left_in2.on();   left_pwm.value  = speed


def backward(speed=TEST_SPEED):
    # ⚠️ MOTOR YÖNÜ TERS ÇEVRİLDİ: Sağ motoru ileri, sol motoru ileri yap (tüm araç ileri gider)
    right_in1.on();  right_in2.off();  right_pwm.value = speed
    left_in1.on();   left_in2.off();   left_pwm.value  = speed


def turn_left(speed=TURN_SPEED):
    """Pivot sol: sağ tekerlek geri, sol tekerlek ileri (motor yönü ters olduğu için)."""
    right_in1.off();  right_in2.on();  right_pwm.value = speed
    left_in1.on();    left_in2.off();  left_pwm.value  = speed


def turn_right(speed=TURN_SPEED):
    """Pivot sağ: sol tekerlek geri, sağ tekerlek ileri (motor yönü ters olduğu için)."""
    right_in1.on();   right_in2.off(); right_pwm.value = speed
    left_in1.off();   left_in2.on();   left_pwm.value  = speed


# --- Otomatik duman testi -------------------------------------------------
def run_smoke_test():
    print("=== Motor Duman Testi ===")
    steps = [
        ("İleri  1 s",    forward,     1.0),
        ("Dur    0.5 s",  stop,        0.5),
        ("Geri   1 s",    backward,    1.0),
        ("Dur    0.5 s",  stop,        0.5),
        ("Sol    0.8 s",  turn_left,   0.8),
        ("Dur    0.3 s",  stop,        0.3),
        ("Sağ    0.8 s",  turn_right,  0.8),
        ("Dur",           stop,        0.0),
    ]
    for label, fn, dur in steps:
        print(f"  {label}")
        fn()
        if dur:
            sleep(dur)
    print("=== Test tamamlandı ===")


# --- İnteraktif klavye kontrolü ------------------------------------------
def run_interactive():
    try:
        import tty
        import termios
    except ImportError:
        print("İnteraktif mod gerçek terminal gerektirir. Duman testi çalıştırılıyor.")
        run_smoke_test()
        return

    fd  = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    print("İnteraktif mod: w/a/s/d = sürüş | BOŞLUK = dur | q = çık")
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if   ch == 'w': forward()
            elif ch == 's': backward()
            elif ch == 'a': turn_left()
            elif ch == 'd': turn_right()
            elif ch == ' ': stop()
            elif ch == 'q': break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        stop()
        print("\nMotorlar durduruldu. Görüşmek üzere.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Motor testi")
    parser.add_argument("--smoke", action="store_true",
                        help="İnteraktif mod yerine otomatik duman testi çalıştır")
    pargs = parser.parse_args()

    try:
        if pargs.smoke:
            run_smoke_test()
        else:
            run_interactive()
    except KeyboardInterrupt:
        stop()
        print("\nKesintiye uğradı.")