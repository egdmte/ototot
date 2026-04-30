#!/usr/bin/env python3
# =============================================================================
# motor_balance_test.py  —  Sol/sağ motor denge kalibrasyonu
#
# Araç düz bir zeminde ilerlerken sapıyorsa bu scripti çalıştır.
# Ölçüm yaparak LEFT_TRIM / RIGHT_TRIM değerlerini hesaplar.
#
# Kullanım:
#   python motor_balance_test.py
#
# Gerekli: Düz zemin (en az 1 metre), cetvel veya mezura
# =============================================================================
import time
import sys

try:
    from motor import MotorDriver
except ImportError:
    print("motor.py bulunamadı. Aynı klasörde çalıştır.")
    sys.exit(1)

TEST_SPEED    = 50    # % — test hızı
TEST_DURATION = 2.0   # saniye — ne kadar ileri gideceği
TRACK_LENGTH  = None  # cm — gerçek mesafe (ölçeceksin)

motor = MotorDriver()

def run_straight_test():
    print("\n" + "="*50)
    print("  MOTOR DENGE TESTİ")
    print("="*50)
    print(f"\nAraç {TEST_DURATION} saniye boyunca {TEST_SPEED}% hızda ileri gidecek.")
    print("Başlamadan önce aracı düz bir çizgiye hizala.")
    print("\nHazır mısın? 3 saniye sonra başlıyor...")
    time.sleep(3)

    motor.set_speed(TEST_SPEED, TEST_SPEED)
    time.sleep(TEST_DURATION)
    motor.brake()
    time.sleep(0.5)

    print("\nAraç durdu.")
    print("Şimdi aracın başlangıç çizgisinden ne kadar saptığını ölç.")
    print("(Sağ sapma = pozitif, Sol sapma = negatif)")
    
    try:
        sapma = float(input("\nSapma miktarı (cm, sağ = +, sol = -): "))
        mesafe = float(input("Toplam ilerlenen mesafe (cm): "))
    except ValueError:
        print("Geçersiz giriş.")
        return

    if mesafe <= 0:
        print("Mesafe sıfırdan büyük olmalı.")
        return

    # Sapma oranı hesabı
    oran = sapma / mesafe

    print(f"\nSapma oranı: {oran:.4f}")
    
    if abs(sapma) < 2:
        print("\n✅ Araç dengeli! Trim değişikliği gerekmiyor.")
        print("   config.py'de LEFT_TRIM = 1.0, RIGHT_TRIM = 1.0 kalabilir.")
        return

    # Trim önerisi
    # Sağa sapıyorsa sağ motor fazla güçlü → RIGHT_TRIM azalt
    # Sola  sapıyorsa sol motor fazla güçlü → LEFT_TRIM  azalt
    if sapma > 0:
        # Sağa sapıyor
        new_right = round(1.0 - abs(oran) * 0.5, 3)
        new_left  = 1.0
        print(f"\n⚠️  Araç SAĞA sapıyor ({sapma:.1f} cm)")
        print(f"   Önerilen trim: LEFT_TRIM = {new_left}, RIGHT_TRIM = {new_right}")
    else:
        # Sola sapıyor
        new_left  = round(1.0 - abs(oran) * 0.5, 3)
        new_right = 1.0
        print(f"\n⚠️  Araç SOLA sapıyor ({sapma:.1f} cm)")
        print(f"   Önerilen trim: LEFT_TRIM = {new_left}, RIGHT_TRIM = {new_right}")

    print("\n📋 config.py'ye şunu yapıştır:")
    print(f"   LEFT_TRIM  = {new_left}")
    print(f"   RIGHT_TRIM = {new_right}")
    print("\nDeğişikliği yaptıktan sonra testi tekrar çalıştırarak doğrula.")


def run_pwm_sweep():
    """Her iki motoru ayrı ayrı test eder — fiziksel fark var mı kontrol eder."""
    print("\n" + "="*50)
    print("  PWM SÜPÜRME TESTİ (tek tek motor)")
    print("="*50)
    
    for side, spd_l, spd_r in [
        ("SOL  motor ileri", 50, 0),
        ("SAĞ  motor ileri", 0,  50),
        ("Her ikisi", 50, 50),
    ]:
        input(f"\n[ENTER] → {side} testi başlasın")
        motor.set_speed(spd_l, spd_r)
        time.sleep(1.5)
        motor.brake()
        time.sleep(0.3)

    print("\nTest bitti. Motor seslerini / hızlarını karşılaştır.")
    print("Belirgin fark varsa fiziksel sorun (motor bağlantısı, direnç) olabilir.")


if __name__ == "__main__":
    print("Motor Denge Kalibrasyonu")
    print("1) Düz gidiş testi (trim hesapla)")
    print("2) PWM süpürme testi (motor fiziksel kontrolü)")
    
    try:
        sec = input("\nSeçim (1/2): ").strip()
        if sec == "1":
            run_straight_test()
        elif sec == "2":
            run_pwm_sweep()
        else:
            print("Geçersiz seçim.")
    except KeyboardInterrupt:
        print("\nKesintiye uğradı.")
    finally:
        motor.stop()
