#!/usr/bin/env python3
# =============================================================================
# kalibrasyon.py  —  SÜPER KOLAY KALİBRASYON MENÜSÜ
#
# Tüm kalibrasyon araçlarını tek menüden çalıştır.
# 
# Kullanım:
#   python kalibrasyon.py
#
# Bu araç sana:
# - Motor dengeleme yapar
# - HSV (beyaz şerit) kalibre eder  
# - Kuş bakışı perspektif ayarlar
# - PD parametreleri tunlar
# - Kameranın gördüklerini gösterir
# =============================================================================
import os
import sys
import time

# Türkçe karakter desteği
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass


def clear_screen():
    """Ekranı temizle."""
    os.system('clear' if os.name == 'posix' else 'cls')


def print_baslik(text):
    """Başlık göster."""
    print()
    print("╔" + "═" * 60 + "╗")
    print(f"║  {text:<58}║")
    print("╚" + "═" * 60 + "╝")
    print()


def bekle(saniye=1):
    """Belirli süre bekle."""
    time.sleep(saniye)


def basinca_devam():
    """Kullanıcı ENTER'a basana kadar bekle."""
    input("\n[ENTER]'a basın...")


# =============================================================================
# 1. MOTOR DENGELEME
# =============================================================================
def motor_dengeleme():
    """Aracı düz gidip ne kadar saptığını ölç."""
    clear_screen()
    print_baslik("1️⃣  MOTOR DENGELEME")
    
    print("📋 BU TEST NE YAPAR?")
    print("─" * 62)
    print("• Araç 2 saniye düz ileri gidecek")
    print("• Sapma miktarını ölçeceksin")
    print("• Program sana yeni TRIM değerlerini söyleyecek")
    print()
    print("📐 HAZIRLIK:")
    print("─" * 62)
    print("1. Aracı düz bir çizgiye hizala")
    print("2. Önünde en az 1.5 metre boşluk olsun")
    print("3. Cetvel veya mezura hazır olsun")
    print()
    
    secim = input("Test başlasın mı? [E/H]: ").strip().lower()
    if secim != 'e' and secim != '':
        print("İptal edildi.")
        bekle()
        return
    
    try:
        from motor import MotorDriver
        motor = MotorDriver()
    except Exception as e:
        print(f"❌ Motor başlatılamadı: {e}")
        basinca_devam()
        return
    
    print("\n3 saniye sonra başlıyor...")
    for i in [3, 2, 1]:
        print(f"  {i}...")
        bekle(1)
    
    print("\n🚗 İLERİ! (2 saniye)")
    motor.set_speed(50, 50)
    bekle(2.0)
    motor.brake()
    bekle(0.5)
    motor.stop()
    
    print("\n✅ Araç durdu!")
    print()
    print("📐 ÖLÇÜM:")
    print("─" * 62)
    print("Şimdi başlangıç çizgisinden ne kadar saptığını ölç.")
    print("• SAĞA saptıysa: pozitif değer (örn: +10)")
    print("• SOLA saptıysa: negatif değer (örn: -10)")
    print("• Düz gittiysе: 0")
    print()
    
    try:
        sapma = float(input("Sapma (cm, sağ=+, sol=-): "))
    except ValueError:
        print("❌ Geçersiz değer.")
        basinca_devam()
        return
    
    print()
    if abs(sapma) < 2:
        print("✅ ARAÇ DENGELİ! TRIM değişikliği gerekmiyor.")
        print("   config.py satır 98-101: 1.0 olarak bırak.")
    elif sapma > 0:
        # Sağa sapıyor → sağ motor güçlü → RIGHT_TRIM azalt
        new_right = round(1.0 - min(0.15, sapma / 100), 3)
        print(f"⚠️  ARAÇ SAĞA SAPIYOR ({sapma:.1f} cm)")
        print()
        print("📋 ÇÖZÜM — config.py'de şu değerleri yaz:")
        print("─" * 62)
        print(f"   RIGHT_TRIM_LOW  = {new_right}    ← satır 100")
        print(f"   RIGHT_TRIM_HIGH = {new_right}    ← satır 101")
    else:
        # Sola sapıyor → sol motor güçlü → LEFT_TRIM azalt
        new_left = round(1.0 - min(0.15, abs(sapma) / 100), 3)
        print(f"⚠️  ARAÇ SOLA SAPIYOR ({abs(sapma):.1f} cm)")
        print()
        print("📋 ÇÖZÜM — config.py'de şu değerleri yaz:")
        print("─" * 62)
        print(f"   LEFT_TRIM_LOW  = {new_left}    ← satır 98")
        print(f"   LEFT_TRIM_HIGH = {new_left}    ← satır 99")
    
    print()
    basinca_devam()


# =============================================================================
# 2. HSV KALİBRASYON (Beyaz Şerit Tespiti) — İNTERAKTİF
# =============================================================================
def hsv_kalibrasyon():
    """İnteraktif HSV ayarlama — slider'larla beyaz şerit eşiklerini bul."""
    clear_screen()
    print_baslik("2️⃣  HSV KALİBRASYON (BEYAZ ŞERİT)")
    
    print("📋 BU TEST NE YAPAR?")
    print("─" * 62)
    print("• Kamera açılır, canlı görüntü gösterilir")
    print("• 6 slider ile HSV eşikleri ayarlanır")
    print("• Beyaz şerit BEYAZ görünmeli, geri kalan SİYAH")
    print()
    print("🎮 KONTROLLER:")
    print("─" * 62)
    print("• Slider'ları ayarla → beyaz şerit ayrılana kadar")
    print("• 's' tuşu → değerleri kaydet ve config.py'ye yaz")
    print("• 'q' tuşu → çık")
    print()
    
    basinca_devam()
    
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("❌ opencv-python kurulu değil")
        basinca_devam()
        return
    
    # Kamera başlat
    try:
        from picamera2 import Picamera2
        camera = Picamera2()
        camera.configure(camera.create_preview_configuration(main={"size": (640, 480), "format": "RGB888"}))
        camera.start()
        time.sleep(1)
        is_picam = True
        print("✅ Pi kamerası açıldı")
    except:
        camera = cv2.VideoCapture(0)
        if not camera.isOpened():
            print("❌ Kamera açılamadı!")
            basinca_devam()
            return
        is_picam = False
        print("✅ USB kamera açıldı")
    
    bekle(1)
    
    # Slider penceresi oluştur
    cv2.namedWindow("HSV Ayarları", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("HSV Ayarları", 400, 300)
    
    # Mevcut değerleri yükle
    try:
        from config import WHITE_HSV_LOW_NORMAL, WHITE_HSV_HIGH_NORMAL
        h_low, s_low, v_low = WHITE_HSV_LOW_NORMAL
        h_high, s_high, v_high = WHITE_HSV_HIGH_NORMAL
    except:
        h_low, s_low, v_low = 0, 0, 120
        h_high, s_high, v_high = 180, 85, 255
    
    cv2.createTrackbar("H Min", "HSV Ayarları", h_low, 180, lambda x: None)
    cv2.createTrackbar("S Min", "HSV Ayarları", s_low, 255, lambda x: None)
    cv2.createTrackbar("V Min", "HSV Ayarları", v_low, 255, lambda x: None)
    cv2.createTrackbar("H Max", "HSV Ayarları", h_high, 180, lambda x: None)
    cv2.createTrackbar("S Max", "HSV Ayarları", s_high, 255, lambda x: None)
    cv2.createTrackbar("V Max", "HSV Ayarları", v_high, 255, lambda x: None)
    
    print("\n🎮 PENCERE AÇILDI — Slider'ları ayarla")
    print("   's' = Kaydet | 'q' = Çık")
    
    while True:
        # Frame al
        if is_picam:
            frame = camera.capture_array()
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        else:
            ret, frame_bgr = camera.read()
            if not ret:
                break
        
        # Slider değerlerini al
        h_low = cv2.getTrackbarPos("H Min", "HSV Ayarları")
        s_low = cv2.getTrackbarPos("S Min", "HSV Ayarları")
        v_low = cv2.getTrackbarPos("V Min", "HSV Ayarları")
        h_high = cv2.getTrackbarPos("H Max", "HSV Ayarları")
        s_high = cv2.getTrackbarPos("S Max", "HSV Ayarları")
        v_high = cv2.getTrackbarPos("V Max", "HSV Ayarları")
        
        # HSV maskeleme
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        v_mean = np.mean(hsv[:, :, 2])
        mask = cv2.inRange(hsv,
                          np.array([h_low, s_low, v_low]),
                          np.array([h_high, s_high, v_high]))
        
        # Sonucu göster
        result = cv2.bitwise_and(frame_bgr, frame_bgr, mask=mask)
        
        # Bilgi yazısı ekle
        info = f"V_mean: {v_mean:.0f} | "
        if v_mean < 100:
            info += "KARANLIK"
        elif v_mean > 200:
            info += "PARLAK"
        else:
            info += "NORMAL"
        cv2.putText(frame_bgr, info, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        
        cv2.putText(mask, "BEYAZ SERIT BURADA OLMALI", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, 200, 2)
        
        # Pencerelerde göster
        cv2.imshow("Orjinal Görüntü", frame_bgr)
        cv2.imshow("Maske (Beyaz=ŞERİT)", mask)
        cv2.imshow("Sonuç", result)
        
        key = cv2.waitKey(30) & 0xFF
        
        if key == ord('q'):
            break
        elif key == ord('s'):
            # Değerleri kaydet
            print()
            print("=" * 62)
            print("✅ HSV DEĞERLERİ KAYDEDİLİYOR...")
            print("=" * 62)
            print()
            print("📋 config.py'de şu değerleri yaz (satır 51-60):")
            print()
            
            if v_mean < 100:
                profile = "DARK"
                line_low = 51
                line_high = 52
            elif v_mean > 200:
                profile = "BRIGHT"
                line_low = 59
                line_high = 60
            else:
                profile = "NORMAL"
                line_low = 55
                line_high = 56
            
            print(f"   # {profile} ortam (V_mean={v_mean:.0f})")
            print(f"   WHITE_HSV_LOW_{profile}  = ({h_low}, {s_low}, {v_low})")
            print(f"   WHITE_HSV_HIGH_{profile} = ({h_high}, {s_high}, {v_high})")
            print()
            
            # config.py'yi güncelle
            try:
                config_path = os.path.join(os.path.dirname(__file__), 'config.py')
                with open(config_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                old_low = f"WHITE_HSV_LOW_{profile}"
                old_high = f"WHITE_HSV_HIGH_{profile}"
                
                # Bu profili otomatik güncelle
                import re
                pattern_low = rf'{old_low}\s*=\s*\([^)]+\)'
                pattern_high = rf'{old_high}\s*=\s*\([^)]+\)'
                
                new_content = re.sub(pattern_low, f'{old_low} = ({h_low}, {s_low}, {v_low})', content, count=1)
                new_content = re.sub(pattern_high, f'{old_high} = ({h_high}, {s_high}, {v_high})', new_content, count=1)
                
                with open(config_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                
                print("✅ config.py OTOMATİK GÜNCELLENDİ!")
                print()
            except Exception as e:
                print(f"⚠️  Otomatik güncelleme başarısız: {e}")
                print("   Yukarıdaki değerleri manuel olarak yaz.")
            
            break
    
    # Temizle
    if is_picam:
        camera.stop()
    else:
        camera.release()
    cv2.destroyAllWindows()
    
    basinca_devam()


# =============================================================================
# 3. KAMERA TESTİ (Canlı Görüntü)
# =============================================================================
def kamera_testi():
    """Kameranın gördüklerini canlı izle."""
    clear_screen()
    print_baslik("3️⃣  KAMERA CANLI GÖRÜNTÜ")
    
    print("📋 BU TEST NE YAPAR?")
    print("─" * 62)
    print("• Kameranın gördüklerini canlı izlersin")
    print("• Şerit takibi nasıl çalışıyor görürsün")
    print("• 'q' tuşu ile çıkarsın")
    print()
    
    basinca_devam()
    
    try:
        os.system(f"{sys.executable} camera.py")
    except Exception as e:
        print(f"❌ Hata: {e}")
        basinca_devam()


# =============================================================================
# 4. PERSPEKTİF KALİBRASYON (Kuş Bakışı)
# =============================================================================
def perspektif_kalibrasyon():
    """Kuş bakışı perspektifin 4 köşesini ayarla."""
    clear_screen()
    print_baslik("4️⃣  PERSPEKTİF KALİBRASYON (KUŞ BAKIŞI)")
    
    print("📋 BU TEST NE YAPAR?")
    print("─" * 62)
    print("• Kameranın gördüklerinden 4 köşeli alan seçersin")
    print("• Bu alan 'kuş bakışı'na dönüştürülür")
    print("• Şerit takibi bu görüntüde yapılır")
    print()
    print("🎮 KONTROLLER:")
    print("─" * 62)
    print("• 4 köşeyi tıkla: sol-üst → sağ-üst → sol-alt → sağ-alt")
    print("• 's' tuşu = kaydet")
    print("• 'r' tuşu = sıfırla")
    print("• 'q' tuşu = çık")
    print()
    
    basinca_devam()
    
    try:
        os.system(f"{sys.executable} calibrate.py")
    except Exception as e:
        print(f"❌ Hata: {e}")
        basinca_devam()


# =============================================================================
# 5. PD PARAMETRE TUNING
# =============================================================================
def pd_tuning():
    """PD parametrelerini interaktif ayarla."""
    clear_screen()
    print_baslik("5️⃣  PD PARAMETRE TUNING (KP/KD)")
    
    print("📋 BU TEST NE YAPAR?")
    print("─" * 62)
    print("• KP (oransal) ve KD (türevsel) kazançlarını ayarla")
    print("• Slider'larla canlı değiştir, etkisini gör")
    print()
    print("📊 PARAMETRELER:")
    print("─" * 62)
    print("• KP yüksek → hızlı tepki ama salınım riski")
    print("• KD yüksek → salınım azalır ama yavaş tepki")
    print()
    print("🎯 DOĞRU AYAR:")
    print("─" * 62)
    print("• Düz gidiş: ±5 piksel salınım")
    print("• Virajlar: hızlı dönüş, salınım yok")
    print()
    
    basinca_devam()
    
    try:
        os.system(f"{sys.executable} pd_tune.py")
    except Exception as e:
        print(f"❌ Hata: {e}")
        basinca_devam()


# =============================================================================
# 6. MOTOR İNTERAKTİF (W/A/S/D)
# =============================================================================
def motor_interaktif():
    """W/A/S/D ile motor kontrol et."""
    clear_screen()
    print_baslik("6️⃣  MOTOR İNTERAKTİF KONTROL (W/A/S/D)")
    
    print("📋 BU TEST NE YAPAR?")
    print("─" * 62)
    print("• Klavye ile motoru kontrol edersin")
    print("• Motor yönü doğru mu test edersin")
    print()
    print("🎮 KONTROLLER:")
    print("─" * 62)
    print("• W = İLERİ")
    print("• S = GERİ")
    print("• A = SOL DÖN")
    print("• D = SAĞ DÖN")
    print("• BOŞLUK = DUR")
    print("• Q = ÇIK")
    print()
    
    basinca_devam()
    
    try:
        os.system(f"{sys.executable} camtester.py")
    except Exception as e:
        print(f"❌ Hata: {e}")
        basinca_devam()


# =============================================================================
# 7. YOL TAKİP (Sadece Şerit)
# =============================================================================
def yol_takip_test():
    """Sadece şerit takibi (olay tespiti yok)."""
    clear_screen()
    print_baslik("7️⃣  YOL TAKİP TEST (SADECE ŞERİT)")
    
    print("📋 BU NE YAPAR?")
    print("─" * 62)
    print("• SADECE şerit takibi yapar")
    print("• Trafik ışığı, yaya geçidi, sollama YOK")
    print("• Pist üzerinde sadece düz/virajlı yolu takip eder")
    print()
    print("🎯 KULLANIM:")
    print("─" * 62)
    print("• Aracı pistin başına koy")
    print("• Konsola GG veya EZ yaz → Araç başlar")
    print("• Şeridi takip eder, dur durmadan gider")
    print("• Ctrl+C ile durdur")
    print()
    print("💡 İPUCU:")
    print("─" * 62)
    print("• Bu mod tamamen şerit takibi testidir")
    print("• Kalibrasyon (HSV, PD) bunda denenmesi rahattır")
    print()
    
    secim = input("Başlatılsın mı? [E/H]: ").strip().lower()
    if secim != 'e':
        return
    
    try:
        os.system(f"{sys.executable} yol_takip.py")
    except Exception as e:
        print(f"❌ Hata: {e}")
    
    basinca_devam()


# =============================================================================
# 8. ANA PROGRAM ÇALIŞTIR
# =============================================================================
def ana_program():
    """Ana sistemi çalıştır."""
    clear_screen()
    print_baslik("8️⃣  ANA PROGRAM ÇALIŞTIR (main.py)")
    
    print("📋 BU NE YAPAR?")
    print("─" * 62)
    print("• Otonom araç sistemi başlatılır")
    print("• Kırmızı ışık beklenir (veya GG/EZ yaz)")
    print()
    print("⚠️  ÖNEMLİ:")
    print("─" * 62)
    print("• Önce diğer kalibrasyonları YAP")
    print("• Aracı pistе koy")
    print("• Konsola GG yazınca araç başlar")
    print()
    
    secim = input("Başlatılsın mı? [E/H]: ").strip().lower()
    if secim != 'e':
        return
    
    try:
        os.system(f"{sys.executable} main.py")
    except Exception as e:
        print(f"❌ Hata: {e}")
    
    basinca_devam()


# =============================================================================
# ANA MENÜ
# =============================================================================
def ana_menu():
    """Ana menüyü göster ve seçim al."""
    while True:
        clear_screen()
        print()
        print("╔" + "═" * 60 + "╗")
        print("║" + " " * 60 + "║")
        print("║" + "    🚗 OTONOM ARAÇ KALİBRASYON MERKEZİ 🚗".center(70) + "║")
        print("║" + " " * 60 + "║")
        print("║" + "         MEB 2026 Robot Yarışması".center(60) + "║")
        print("║" + " " * 60 + "║")
        print("╚" + "═" * 60 + "╝")
        print()
        print("📋 KALİBRASYON ARAÇLARI:")
        print("─" * 62)
        print()
        print("  1️⃣   Motor Dengeleme        (Düz gidiyor mu?)")
        print("  2️⃣   HSV Kalibrasyon ⭐     (Beyaz şerit bulma)")
        print("  3️⃣   Kamera Canlı İzle      (Görüntü kontrolü)")
        print("  4️⃣   Perspektif Kalibrasyon (Kuş bakışı)")
        print("  5️⃣   PD Parametre Tuning    (Direksiyon tepkisi)")
        print("  6️⃣   Motor İnteraktif       (W/A/S/D kontrol)")
        print()
        print("─" * 62)
        print()
        print("  7️⃣   YOL TAKİP TEST       🚗 (Sadece şerit takibi)")
        print("  8️⃣   ANA PROGRAM ÇALIŞTIR  (main.py - tüm görevler)")
        print()
        print("  0    ÇIK")
        print()
        print("─" * 62)
        print("⭐ = Şu anki sorununa en yakın çözüm")
        print()
        
        try:
            secim = input("Seçim [0-8]: ").strip()
        except KeyboardInterrupt:
            print("\n\nÇıkılıyor...")
            break
        
        if secim == '0':
            print("\n✅ Görüşmek üzere!")
            break
        elif secim == '1':
            motor_dengeleme()
        elif secim == '2':
            hsv_kalibrasyon()
        elif secim == '3':
            kamera_testi()
        elif secim == '4':
            perspektif_kalibrasyon()
        elif secim == '5':
            pd_tuning()
        elif secim == '6':
            motor_interaktif()
        elif secim == '7':
            yol_takip_test()
        elif secim == '8':
            ana_program()
        else:
            print(f"\n❌ Geçersiz seçim: {secim}")
            bekle(1.5)


if __name__ == "__main__":
    try:
        ana_menu()
    except KeyboardInterrupt:
        print("\n\nÇıkılıyor...")
    except Exception as e:
        print(f"\n❌ Hata: {e}")
        import traceback
        traceback.print_exc()
