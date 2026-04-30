# =============================================================================
# motor.py  —  Düşük seviyeli H-köprüsü motor sürücüsü  (gpiozero — Pi 5 uyumlu)
# =============================================================================
try:
    from gpiozero import DigitalOutputDevice, PWMOutputDevice
    _HAS_GPIO = True
except ImportError:
    _HAS_GPIO = False
    print("[motor] gpiozero bulunamadı — simülasyon modunda çalışıyor (hareket yok)")

    class DigitalOutputDevice:  # type: ignore[no-redef]
        def __init__(self, pin): pass
        def on(self):    pass
        def off(self):   pass
        def close(self): pass

    class PWMOutputDevice:      # type: ignore[no-redef]
        def __init__(self, pin): self.value = 0.0
        def close(self):         pass

from config import (
    RIGHT_IN1, RIGHT_IN2, LEFT_IN1, LEFT_IN2,
    LEFT_PWM_PIN, RIGHT_PWM_PIN,
    LEFT_TRIM_LOW, LEFT_TRIM_HIGH,
    RIGHT_TRIM_LOW, RIGHT_TRIM_HIGH,
)


class MotorDriver:
    """İki DC motoru H-köprüsü üzerinden (örn. L298N) kontrol eder.

    Hız değerleri [-100, 100] aralığındadır:
      pozitif → ileri, negatif → geri, 0 → serbest.
    gpiozero yoksa tüm çağrılar sessizce görmezden gelinir.
    """

    def __init__(self):
        self._has_gpio = _HAS_GPIO
        if not self._has_gpio:
            return
        self._right_in1 = DigitalOutputDevice(RIGHT_IN1)
        self._right_in2 = DigitalOutputDevice(RIGHT_IN2)
        self._left_in1  = DigitalOutputDevice(LEFT_IN1)
        self._left_in2  = DigitalOutputDevice(LEFT_IN2)
        # PWMOutputDevice değer aralığı 0.0 – 1.0
        self._right_pwm = PWMOutputDevice(RIGHT_PWM_PIN)
        self._left_pwm  = PWMOutputDevice(LEFT_PWM_PIN)

    # ------------------------------------------------------------------
    def set_speed(self, left: float, right: float) -> None:
        """[-100, 100] aralığında tekerlek hızlarını uygular.

        Hız-bağımlı TRIM uygulanır:
        - < 40%: LOW profili
        - > 70%: HIGH profili
        - Arası: lineer interpolasyon
        """
        if not self._has_gpio:
            return
        
        left  = float(left)
        right = float(right)
        
        # Hız-bağımlı trim seçimi
        left_trim = self._get_trim(left, LEFT_TRIM_LOW, LEFT_TRIM_HIGH)
        right_trim = self._get_trim(right, RIGHT_TRIM_LOW, RIGHT_TRIM_HIGH)
        
        left  = left * left_trim
        right = right * right_trim
        left  = max(-100.0, min(100.0, left))
        right = max(-100.0, min(100.0, right))
        self._apply(self._left_in1,  self._left_in2,  self._left_pwm,  left)
        self._apply(self._right_in1, self._right_in2, self._right_pwm, right)

    # ------------------------------------------------------------------
    @staticmethod
    def _get_trim(pwm: float, trim_low: float, trim_high: float) -> float:
        """Hız profiline göre trim değeri döndür (lineer interpolasyon)."""
        abs_pwm = abs(pwm)
        
        if abs_pwm < 40:
            return trim_low
        elif abs_pwm > 70:
            return trim_high
        else:
            # Lineer interpolasyon: 40% ile 70% arasında
            ratio = (abs_pwm - 40) / 30.0
            return trim_low + ratio * (trim_high - trim_low)

    # ------------------------------------------------------------------
    def brake(self) -> None:
        """Aktif fren: her iki yön pini HIGH, PWM kapalı."""
        if not self._has_gpio:
            return
        for pin in (self._right_in1, self._right_in2,
                    self._left_in1,  self._left_in2):
            pin.on()
        self._right_pwm.value = 0
        self._left_pwm.value  = 0

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Serbest frenleme ve tüm GPIO kaynaklarını serbest bırakma."""
        if not self._has_gpio:
            return
        self._right_pwm.value = 0
        self._left_pwm.value  = 0
        for dev in (self._right_in1, self._right_in2,
                    self._left_in1,  self._left_in2,
                    self._right_pwm, self._left_pwm):
            try:
                dev.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    @staticmethod
    def _apply(
        pin_fwd: "DigitalOutputDevice",
        pin_rev: "DigitalOutputDevice",
        pwm:     "PWMOutputDevice",
        speed:   float,
    ) -> None:
        # ⚠️ MOTOR YÖNÜ TERSİ ÇEVRİLDİ (ileri↔geri)
        if speed >= 0:
            # Pozitif → GERI (pin_rev ON)
            pin_fwd.off()
            pin_rev.on()
        else:
            # Negatif → İLERİ (pin_fwd ON)
            pin_fwd.on()
            pin_rev.off()
        pwm.value = abs(speed) / 100.0