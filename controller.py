# =============================================================================
# controller.py  —  PD direksiyon denetleyicisi — OPTIMIZE EDİLMİŞ
#                   + Hız-Viraj Koordinasyonu
#                   + Dinamik Kazanç (Büyük Hatalar)
#                   + Ölü Bölge Telafisi
# =============================================================================
import math
import time

import numpy as np

from config import (
    KP, KD, KI, INTEGRAL_MAX, BASE_SPEED, MIN_SPEED, MAX_SPEED, K_SPEED,
    KP_LARGE_ERROR_MULT, KD_LARGE_ERROR_MULT,
    DERIV_CAP, CROSSING_KD_MULT,
    DERIV_SLOWDOWN_THRESHOLD, DERIV_MEDIUM_THRESHOLD,
    LEFT_TRIM_LOW, LEFT_TRIM_HIGH,
    RIGHT_TRIM_LOW, RIGHT_TRIM_HIGH,
    DEAD_ZONE_MIN_PWM,
    STEERING_RATE_LIMIT,
)

# Kaç ardışık kayıp kare sonra tamamen duralım
_LOST_FRAMES_STOP = 30


class PDController:
    """Yanal piksel hatasını diferansiyel tekerlek hızlarına dönüştüren PD denetleyici.

    hata > 0  →  araç şerit merkezinin SAĞında  →  sola dön
    hata < 0  →  araç şerit merkezinin SOLunda  →  sağa dön
    """

    def __init__(self):
        self.prev_error:    float = 0.0
        self.prev_time:     float = time.time()
        self.lost_frames:   int   = 0
        self.integral:      float = 0.0
        # Direksiyon rate limit için son uygulanan düzeltme
        self.prev_correction: float = 0.0
        # Dış kontrol (watchdog) hata müdahalesi için hız çarpanı
        self.speed_multiplier: float = 1.0

    # ------------------------------------------------------------------
    def compute(self, error) -> tuple:
        """(sol_hız, sağ_hız) tuple'ı döndürür, her biri yüzde [0, 100].

        Şerit görünmüyorsa error=None geçin; araç yavaşlar ve
        son direksiyon yönünü korur.
        
        OPTIMIZASYONLAR:
        - Hız-Viraj Koordinasyonu: Derivative bazlı yavaşlama
        - Dinamik Kazanç: Büyük hatalar için KP/KD çarpanı
        - Ölü Bölge Telafisi: PWM sinyalini offset et
        """
        now = time.time()
        dt  = max(now - self.prev_time, 1e-3)

        if error is None:
            self.lost_frames += 1
            error = self.prev_error * 0.8   # giderek düzleşir
            error_for_integration = None    # integratörü dondur
        else:
            self.lost_frames = 0
            error_for_integration = error

        # Derivative hesabı + Cap (salınım önleme)
        derivative = (error - self.prev_error) / dt
        derivative = float(np.clip(derivative, -DERIV_CAP, DERIV_CAP))

        # İntegral + anti-windup (yalnızca güvenilir error'da biriktir)
        if error_for_integration is not None:
            self.integral += error_for_integration * dt
            self.integral = float(np.clip(self.integral, -INTEGRAL_MAX, INTEGRAL_MAX))

        # Hız-Viraj Koordinasyonu: Derivative bazlı hız kontrol
        # Hem düzde salınım hem de keskin viraj girişinde türev büyüdüğünde yavaşla.
        speed = float(BASE_SPEED - K_SPEED * abs(error))

        if abs(derivative) > DERIV_SLOWDOWN_THRESHOLD:
            speed = MIN_SPEED
        elif abs(derivative) > DERIV_MEDIUM_THRESHOLD:
            speed = BASE_SPEED - 10

        speed = float(np.clip(speed, MIN_SPEED, MAX_SPEED))

        # Dinamik Kazanç: Büyük hatalar için KP/KD çarpanı
        kp_eff = KP
        kd_eff = KD

        if abs(error) > 30:
            kp_eff *= KP_LARGE_ERROR_MULT
            kd_eff *= KD_LARGE_ERROR_MULT

        # Crossing (viraj) için KD artırma
        if abs(derivative) > 50:
            kd_eff *= CROSSING_KD_MULT

        # Direksiyon düzeltme hesabı (PID)
        correction = kp_eff * error + KI * self.integral + kd_eff * derivative

        # ===== DIREKSİYON RATE LIMIT (yalpa önleme) =====
        # Tek karede düzeltme en fazla STEERING_RATE_LIMIT kadar değişebilir.
        # Gürültülü bir error frame'i motora 100% diferansiyel olarak yansıtmaz.
        delta_corr = correction - self.prev_correction
        if abs(delta_corr) > STEERING_RATE_LIMIT:
            delta_corr = math.copysign(STEERING_RATE_LIMIT, delta_corr)
            correction = self.prev_correction + delta_corr
        self.prev_correction = correction

        if self.lost_frames > _LOST_FRAMES_STOP:
            speed = 0.0
            self.integral = 0.0   # tam durunca biriken bias'ı temizle
            self.prev_correction = 0.0

        # Watchdog/dış hız çarpanı (FPS düşük/lane lost gibi durumlar)
        speed *= float(np.clip(self.speed_multiplier, 0.0, 1.0))

        # Ham tekerlek hızları (clip + ölü bölge telafisi pair olarak yapılır)
        left_raw  = speed + correction
        right_raw = speed - correction

        # Ölü Bölge Telafisi: common-mode'u kaldır, diferansiyeli koru
        left, right = self._apply_dead_zone_pair(left_raw, right_raw)

        # Hız profiline göre trim seçimi
        left = self._apply_speed_dependent_trim(left)
        right = self._apply_speed_dependent_trim(right)

        self.prev_error = error
        self.prev_time  = now

        return left, right

    # ------------------------------------------------------------------
    def _apply_dead_zone_pair(self, left: float, right: float) -> tuple:
        """İki tekerleğe birlikte ölü bölge telafisi.

        Eski sürüm her tekeri bağımsız ±DEAD_ZONE_MIN_PWM'e çekiyordu →
        küçük diferansiyel komutlar (ör. 20 / 10) ikisi de 30/30'a yuvarlanıp
        bias yok oluyordu. Bu sürüm common-mode bileşeni kaldırır,
        diferansiyeli (yön komutu) bozmadan korur.

        Aynı işaretli tekerleklerde common+diff ayrıştırması; karşıt işaretli
        (pivot) durumda her tekeri bağımsız kaldırır.
        """
        # İkisi de tam sıfırsa dokunma
        if left == 0.0 and right == 0.0:
            return 0.0, 0.0

        same_sign = (left >= 0 and right >= 0) or (left <= 0 and right <= 0)

        if same_sign:
            common = (left + right) / 2.0
            diff   = (left - right) / 2.0
            if common != 0.0 and abs(common) < DEAD_ZONE_MIN_PWM:
                common = math.copysign(DEAD_ZONE_MIN_PWM, common)
            left_out  = common + diff
            right_out = common - diff
            # İkinci geçiş: ortak-mod yükseltmesi sonrasında ayrı tekerlekler
            # hâlâ ölü bölgedeyse bağımsız kaldır (diferansiyel yön korunur).
            if 0 < abs(left_out) < DEAD_ZONE_MIN_PWM:
                left_out = math.copysign(DEAD_ZONE_MIN_PWM, left_out)
            if 0 < abs(right_out) < DEAD_ZONE_MIN_PWM:
                right_out = math.copysign(DEAD_ZONE_MIN_PWM, right_out)
        else:
            # Pivot — tekerlekler ters yönde, bağımsız kaldır
            left_out  = (math.copysign(DEAD_ZONE_MIN_PWM, left)
                         if 0 < abs(left) < DEAD_ZONE_MIN_PWM else left)
            right_out = (math.copysign(DEAD_ZONE_MIN_PWM, right)
                         if 0 < abs(right) < DEAD_ZONE_MIN_PWM else right)

        return (float(np.clip(left_out,  -MAX_SPEED, MAX_SPEED)),
                float(np.clip(right_out, -MAX_SPEED, MAX_SPEED)))

    # ------------------------------------------------------------------
    def _apply_speed_dependent_trim(self, pwm: float) -> float:
        """Hız profiline göre LEFT/RIGHT trim seçimi."""
        abs_pwm = abs(pwm)
        
        if abs_pwm < 40:
            # Düşük hız profili
            trim = LEFT_TRIM_LOW if pwm >= 0 else RIGHT_TRIM_LOW
        elif abs_pwm > 70:
            # Yüksek hız profili
            trim = LEFT_TRIM_HIGH if pwm >= 0 else RIGHT_TRIM_HIGH
        else:
            # Lineer interpolasyon
            ratio = (abs_pwm - 40) / 30.0
            if pwm >= 0:
                trim = LEFT_TRIM_LOW + ratio * (LEFT_TRIM_HIGH - LEFT_TRIM_LOW)
            else:
                trim = RIGHT_TRIM_LOW + ratio * (RIGHT_TRIM_HIGH - RIGHT_TRIM_LOW)
        
        return pwm * trim

    # ------------------------------------------------------------------
    def reset(self) -> None:
        """İç durumu sıfırla (örn. bir duraklamadan sonra)."""
        self.prev_error      = 0.0
        self.prev_time       = time.time()
        self.lost_frames     = 0
        self.integral        = 0.0
        self.prev_correction = 0.0
        self.speed_multiplier = 1.0