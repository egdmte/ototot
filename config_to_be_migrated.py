# =============================================================================
# config.py  â  TÃ¼m ayarlanabilir parametreler tek yerden
#
# YarÄ±Å gÃ¼nÃ¼ Ã¶nce calibrate.py, sonra camera.py Ã§alÄ±ÅtÄ±r,
# deÄerleri buraya yapÄ±ÅtÄ±r, sistemi baÅlat.
# =============================================================================

# ---------------------------------------------------------------------------
# Kamera Ã§Ã¶zÃ¼nÃ¼rlÃ¼ÄÃ¼
# ---------------------------------------------------------------------------
WIDTH  = 800
HEIGHT = 680

# ---------------------------------------------------------------------------
# Perspektif / ROI
# ---------------------------------------------------------------------------
# GÃ¶rÃ¼ntÃ¼nÃ¼n alttan itibaren kaÃ§ta kaÃ§Ä±nÄ± kullanalÄ±m (0.55 â Ã¼st %45 atÄ±lÄ±r).
ROI_TOP_RATIO = 0.55

# Perspektif dÃ¶rtgeni â TAM KARE piksel koordinatlarÄ±.
# SÄ±ra: sol-Ã¼st, saÄ-Ã¼st, sol-alt, saÄ-alt
# GerÃ§ek pistinize gÃ¶re calibrate.py ile ayarlayÄ±n.
PERSP_SRC = [[160, 300], [480, 300],  [0,   480],   [640, 480]]

# ---------------------------------------------------------------------------
# Åerit tespiti
# ---------------------------------------------------------------------------
# Histogramda minimum sÃ¼tun toplamÄ± â Åerit tepe noktasÄ± geÃ§erliliÄi iÃ§in.
MIN_LANE_SIGNAL = 200

# Åerit Kalitesi KontrolÃ¼: Histogram tepe noktasÄ± sinyal gÃ¼venliÄi
MIN_LANE_SIGNAL_QUALITY_RATIO = 1.0  # max(hist) < MIN_LANE_SIGNAL * 1.5 ise red et

# YalnÄ±zca bir Åerit gÃ¶rÃ¼nÃ¼yorken kullanÄ±lan varsayÄ±lan Åerit geniÅliÄi (px).
# GerÃ§ek pistinizde camera.py ile Ã¶lÃ§Ã¼n.
ASSUMED_LANE_WIDTH = 300

# Beyaz Åerit iÃ§in HSV aralÄ±ÄÄ±.
# camera.py'de tesis Ä±ÅÄ±ÄÄ± altÄ±nda doÄrulayÄ±n.
# ADAPTIF HSV: ParlaklÄ±k ortalamasÄ±na gÃ¶re dinamik ayarlama
WHITE_HSV_LOW  = (0,   0,  140)
WHITE_HSV_HIGH = (180, 80, 255)

# Adaptif HSV profilleri (V_mean'e gÃ¶re otomatik seÃ§im)
# KaranlÄ±k: V_mean < 100
WHITE_HSV_LOW_DARK   = (0,   0,  80)
WHITE_HSV_HIGH_DARK  = (180, 100, 255)

# Normal: 100 <= V_mean <= 200
WHITE_HSV_LOW_NORMAL = (0,   0,  90)   
WHITE_HSV_HIGH_NORMAL = (180, 110, 255) 

# Parlak: V_mean > 200
WHITE_HSV_LOW_BRIGHT = (0,   0,  160)
WHITE_HSV_HIGH_BRIGHT = (180, 60, 255)

# Åerit sinyali MIN_LANE_SIGNAL'Ä±n altÄ±na dÃ¼ÅtÃ¼kten sonra kaÃ§ kare gÃ¼venilir.
LANE_MEMORY_FRAMES = 25

# Son bilinen konumdan kaÃ§ piksel iÃ§inde arama yapÄ±lÄ±r.
LANE_SEARCH_WINDOW = 120

# ---------------------------------------------------------------------------
# PD denetleyici â OPTIMIZE EDÄ°LMÄ°Å
# ---------------------------------------------------------------------------
KP = 0.30   # oransal kazanÃ§
KD = 0.45   # tÃ¼revsel kazanÃ§ â dÃ¼ÅÃ¼k tutuldu (salÄ±nÄ±m Ã¶nleme)

# Ä°ntegral kazancÄ± + anti-windup
# SÃ¼rekli virajda PD'nin sÄ±fÄ±rlayamadÄ±ÄÄ± kalÄ±cÄ± hatayÄ± kapatÄ±r.
# INTEGRAL_MAX kÃ¼Ã§Ã¼k tutulur ki dÄ±Å-yÃ¶rÃ¼ngeye sÃ¼rÃ¼klenmeyi dÃ¼zeltsin ama
# uzun dÃ¼z hatlarda biriken bias'la salÄ±nÄ±ma yol aÃ§masÄ±n.
KI           = 0.04
INTEGRAL_MAX = 50.0

# BÃ¼yÃ¼k hatalar iÃ§in dinamik kazanÃ§ artÄ±ÅÄ± â DEVRE DIÅI (1.0 = etki yok)
# SalÄ±nÄ±ma neden oluyordu; sade PD daha kararlÄ±.
KP_LARGE_ERROR_MULT = 1.0
KD_LARGE_ERROR_MULT = 1.0

# Derivative cap (salÄ±nÄ±m Ã¶nleme) â dÃ¼ÅÃ¼rÃ¼ldÃ¼
DERIV_CAP = 150

# Crossing (viraj) iÃ§in KD artÄ±rma â DEVRE DIÅI
# KD_LARGE_ERROR_MULT * CROSSING_KD_MULT zincirlenerek efektif KD=1.18 yapÄ±yordu.
CROSSING_KD_MULT = 1.0

# ---------------------------------------------------------------------------
# Motor hÄ±zlarÄ± (0â100 %) â OPTIMIZE EDÄ°LMÄ°Å
# ---------------------------------------------------------------------------
BASE_SPEED = 62   # hata = 0 iken seyir hÄ±zÄ±
MIN_SPEED  = 25   # minimum hÄ±z (virajda durmama)
MAX_SPEED  = 85   # maksimum hÄ±z
K_SPEED    = 0.28 # hÄ±z = BASE - K_SPEED * |hata|

# HÄ±z-Viraj Koordinasyonu: Derivative bazlÄ± yavaÅlama
DERIV_SLOWDOWN_THRESHOLD = 50   # |derivative| > 50 ise MIN_SPEED'e
DERIV_MEDIUM_THRESHOLD   = 30   # |derivative| > 30 ise BASE - 10

# TÃ¼rev yavaÅlamasÄ±nÄ± yalnÄ±zca merkeze yakÄ±n salÄ±nÄ±mda tetikle.
# |error| bu eÅiÄin Ã¼stÃ¼ndeyse araba zaten viraja giriyor demektir; bu anda
# yavaÅlamak yÃ¶n otoritesini kaybettirir, yavaÅlatma kapatÄ±lÄ±r.
DERIV_SLOWDOWN_ERROR_GATE = 25

# Motor dengeleme katsayÄ±larÄ± â mekanik dengesizliÄi giderir.
# DÃ¼ÅÃ¼k hÄ±zda (< 40%) ve yÃ¼ksek hÄ±zda (> 70%) ayrÄ± profiller
LEFT_TRIM_LOW   = 1.0   # < 40% hÄ±zda sol trim
LEFT_TRIM_HIGH  = 1.0   # > 70% hÄ±zda sol trim
RIGHT_TRIM_LOW  = 1.0   # < 40% hÄ±zda saÄ trim
RIGHT_TRIM_HIGH = 1.0   # > 70% hÄ±zda saÄ trim

# ÃlÃ¼ bÃ¶lge telafisi (20% Ã¶lÃ¼ bÃ¶lge)
DEAD_ZONE_PERCENT = 20   # PWM sinyalinin Ã¼st % kaÃ§Ä± Ã¶lÃ¼ bÃ¶lge
DEAD_ZONE_MIN_PWM = 30   # ÃlÃ¼ bÃ¶lgeyi aÅan minimum PWM

# ---------------------------------------------------------------------------
# GPIO pinleri (BCM numaralandÄ±rmasÄ±)
# ---------------------------------------------------------------------------
RIGHT_IN1     = 17
RIGHT_IN2     = 27
LEFT_IN1      = 22
LEFT_IN2      = 23
LEFT_PWM_PIN  = 12
RIGHT_PWM_PIN = 13

# Fiziksel baÅlatma butonu (BCM).
# YarÄ±Åta bilgisayarsÄ±z baÅlatma â +50 puan bonusu.
START_BUTTON_PIN = 16

# ---------------------------------------------------------------------------
# Kamera renk sÄ±rasÄ± dÃ¼zeltme
# ---------------------------------------------------------------------------
# BazÄ± Raspberry Pi / picamera2 donanÄ±m+sÃ¼rÃ¼m kombinasyonlarÄ±nda
# "RGB888" formatÄ± talep edilmesine raÄmen kare BGRA veya BGR sÄ±ralÄ± gelebilir.
# Kameradan gelen gÃ¶rÃ¼ntÃ¼nÃ¼n RENK KANALLARI TERS gÃ¶rÃ¼nÃ¼yorsa (beyaz mavi gibi,
# turuncu mavi gibi) bu bayraÄÄ± True yapÄ±n.
CAMERA_BGR_OUTPUT  = False   # True â kamera BGR dÃ¶nÃ¼yor, RGB'ye Ã§evir
CAMERA_ROTATE_180  = True   # True â kamera 180Â° dÃ¶ndÃ¼rÃ¼lÃ¼r (ters montaj)

# SÃ¼rÃ¼Å sÄ±rasÄ±nda Ã¶nizleme penceresi (main.py). False = performans modu.
SHOW_PREVIEW = True

# ---------------------------------------------------------------------------
# KayÄ±t
# ---------------------------------------------------------------------------
LOG_DURATION_SEC = 120
LOG_FILE         = "error_log.csv"

# ---------------------------------------------------------------------------
# Olay tespiti â ROI'lar
# ---------------------------------------------------------------------------
# Trafik Ä±ÅÄ±ÄÄ± / levha iÃ§in Ã¼st ROI
SIGNAL_ROI_TOP    = 0
SIGNAL_ROI_BOTTOM = 200

# Yol yÃ¼zeyi olaylarÄ± (yaya geÃ§idi, hemzemin, tÃ¼msek) iÃ§in alt ROI
ROAD_ROI_TOP    = 300
ROAD_ROI_BOTTOM = 480

# ---------------------------------------------------------------------------
# Trafik Ä±ÅÄ±ÄÄ± renkleri â HSV
# ---------------------------------------------------------------------------
# KIRMIZI: ton Ã§ift aralÄ±klÄ±dÄ±r (0-10 ve 160-180)
RED_HSV_LOW1  = (0,   120, 80)
RED_HSV_HIGH1 = (10,  255, 255)
RED_HSV_LOW2  = (160, 120, 80)
RED_HSV_HIGH2 = (180, 255, 255)

# YEÅÄ°L
GREEN_HSV_LOW  = (40,  80, 60)
GREEN_HSV_HIGH = (90, 255, 255)

# GeÃ§erli sinyal blobu iÃ§in minimum kontur alanÄ± (pxÂ²)
SIGNAL_MIN_AREA = 300

# ---------------------------------------------------------------------------
# Yaya geÃ§idi / hemzemin geÃ§it tespiti
# ---------------------------------------------------------------------------
# KaÃ§ adet yatay beyaz bant = yaya geÃ§idi
# â ï¸ ÃNEMLÄ°: DÃ¼ÅÃ¼k deÄer (2) dÃ¼z yolu da yaya geÃ§idi sanÄ±r!
# GerÃ§ek yaya geÃ§idinde 4-6 bant vardÄ±r.
CROSSWALK_MIN_STRIPES = 4

# Hemzemin X-deseni: her Ã§apraz yÃ¶nde en az kaÃ§ Ã§izgi olmalÄ±
HEMZEMIN_DIAG_MIN_LINES = 2

# ---------------------------------------------------------------------------
# Olay debounce
# ---------------------------------------------------------------------------
# Bir olay kaÃ§ ardÄ±ÅÄ±k karede gÃ¶rÃ¼nmeli ki gerÃ§ek kabul edilsin
EVENT_DEBOUNCE_FRAMES = 6

# Olay "yakÄ±n" sayÄ±lmasÄ± iÃ§in road ROI'nun bu orandan sonraki alt diliminde
# desenin gÃ¶rÃ¼nmesi gerekir (0.75 = ROI'nun alt %25'i = ~30 cm).
# Yaya geÃ§idi ve hemzemin iÃ§in "30 cm Ã¶nce dur" kuralÄ± (3.4.2, 3.4.4).
EVENT_NEAR_ROI_RATIO = 0.75

# ---------------------------------------------------------------------------
# Åerit kayÄ±p failsafe
# ---------------------------------------------------------------------------
# Åerit algÄ±lanamadÄ±ÄÄ±nda (bÃ¼yÃ¼k beyaz leke / zemin) araÃ§ sola dÃ¶nmeye baÅlar.
# LANE_LOST_TURN_SEC saniye iÃ§inde Åerit tekrar bulunmazsa araÃ§ durur.
LANE_LOST_TURN_SEC  = 3.5   # sola dÃ¶nÃ¼Å sÃ¼resi (s) â arabaya gÃ¶re ayarla
LANE_LOST_TURN_BIAS = 100   # sol dÃ¶nÃ¼Å iÃ§in yapay hata (px; + = sola dÃ¶n)

# ---------------------------------------------------------------------------
# Durum makinesi zamanlamasÄ±
# ---------------------------------------------------------------------------
CROSSWALK_WAIT_SEC  = 5.0   # yaya geÃ§idinde bekleme (kural: â¥5 s)
HEMZEMIN_WAIT_SEC   = 5.0   # hemzemin geÃ§itte bekleme (kural: â¥5 s)
SPEED_BUMP_SLOW_SEC = 1.5   # tÃ¼msek Ã¼zerinde yavaÅ geÃ§iÅ sÃ¼resi
SPEED_BUMP_SPEED    = 25    # tÃ¼msek geÃ§iÅi sÄ±rasÄ±nda hÄ±z (%)

# YaklaÅma hÄ±zÄ±: yaya geÃ§idi/hemzemin tespit edildi ama henÃ¼z yakÄ±n deÄil
# durumunda kullanÄ±lÄ±r. Åerit takibi aÃ§Ä±k kalÄ±r, sadece hÄ±z dÃ¼Åer.
APPROACH_SPEED       = 35
APPROACH_TIMEOUT_SEC = 4.0   # yaklaÅma fazÄ± bu sÃ¼reyi aÅarsa fallback fren

# ---------------------------------------------------------------------------
# Turuncu engel araÃ§ (sollama â 20Ã30Ã25 cm)
# ---------------------------------------------------------------------------
ORANGE_HSV_LOW  = (5,  140, 80)
ORANGE_HSV_HIGH = (20, 255, 255)  # H Ã¼st sÄ±nÄ±rÄ± 20 â sarÄ± ton (Hâ¥22) ile Ã§akÄ±Åmaz
ORANGE_MIN_AREA = 1500   # pxÂ² â tetiklemek iÃ§in minimum blob alanÄ±

# ---------------------------------------------------------------------------
# Sollama manevra parametreleri
# ---------------------------------------------------------------------------
OVERTAKING_STEER_BIAS = 60   # sola geÃ§iÅ iÃ§in px cinsinden yapay hata
OVERTAKING_CROSS_SEC  = 1.2  # merkez Ã§izgiyi geÃ§me sÃ¼resi (s)
OVERTAKING_PASS_SEC   = 2.5  # turuncu aracÄ±n yanÄ±ndan geÃ§me sÃ¼resi (s)
OVERTAKING_RETURN_SEC = 1.2  # saÄ Åeride dÃ¶nme sÃ¼resi (s)
OVERTAKING_SPEED      = 40   # sollama sÄ±rasÄ±nda hÄ±z (%)

# ---------------------------------------------------------------------------
# Park etme (kÄ±rmÄ±zÄ± slot â her zaman kÄ±rmÄ±zÄ±, PDF'te onaylÄ±)
# ---------------------------------------------------------------------------
PARKING_HSV_LOW1  = (0,   120, 80)
PARKING_HSV_HIGH1 = (10,  255, 255)
PARKING_HSV_LOW2  = (160, 120, 80)
PARKING_HSV_HIGH2 = (180, 255, 255)
PARKING_MIN_AREA     = 3000   # park manevrasÄ± sÄ±rasÄ±nda min kÄ±rmÄ±zÄ± blob alanÄ±
PARKING_TRIGGER_AREA = 6000   # PARKING durumuna geÃ§mek iÃ§in eÅik alanÄ±
PARKING_ROI_TOP      = 240    # kÄ±rmÄ±zÄ± slotlarÄ± aramak iÃ§in alt ROI y baÅlangÄ±cÄ±
# Park bÃ¶lgesi tetikleyicisi: kÄ±rmÄ±zÄ± blobun bbox alt-kenarÄ± ROI'nin bu oranÄ±ndan
# bÃ¼yÃ¼k olmalÄ± (yakÄ±n olduÄunu garanti eder, uzaktaki kÄ±rmÄ±zÄ± objelere takÄ±lmaz).
# AyrÄ±ca turuncu engel aynÄ± karede varsa park tetiklenmez (renk overlap korumasÄ±).
PARKING_NEAR_BOTTOM_RATIO = 0.70
PARKING_SPEED        = 30     # park ederken hÄ±z (%)
PARKING_CENTER_TOL   = 40     # kare merkezine px cinsinden tolerans

# ---------------------------------------------------------------------------
# SarÄ± araÃ§ â sollama YASAÄI bÃ¶lgesinde karÅÄ± Åerit engeli (20Ã45Ã25 cm)
# ---------------------------------------------------------------------------
# Kural: sarÄ± araÃ§lar (20Ã45Ã25 cm) sollama yasaÄÄ± bÃ¶lgesine yerleÅtirilir.
# Turuncu ile Ã§akÄ±ÅmamasÄ± iÃ§in Hâ¥22'den baÅlÄ±yoruz.
YELLOW_HSV_LOW  = (22, 100, 80)
YELLOW_HSV_HIGH = (38, 255, 255)
YELLOW_MIN_AREA = 1500   # SarÄ± blob iÃ§in minimum alan (pxÂ²)

# ---------------------------------------------------------------------------
# Levha (iÅaret tabelasÄ±) tespiti â sinyal ROI iÃ§inde
# ---------------------------------------------------------------------------
# Mavi arka planlÄ± levhalar: Park (P) ve ÃÄ±kmaz Yol (T) iÅaretleri
# KÄ±lavuza gÃ¶re levha boyutu: 13 cm geniÅlik, toplam 20 cm yÃ¼kseklik (sap dahil)
SIGN_BLUE_HSV_LOW  = (100, 120, 80)   # Mavi levha alt HSV eÅiÄi
SIGN_BLUE_HSV_HIGH = (130, 255, 255)  # Mavi levha Ã¼st HSV eÅiÄi
SIGN_MIN_AREA      = 200              # KÃ¼Ã§Ã¼k levhalar iÃ§in dÃ¼ÅÃ¼k alan eÅiÄi (pxÂ²)

# ---------------------------------------------------------------------------
# YansÄ±ma direnci â CLAHE + sÃ¼tun sÃ¼rekliliÄi (lane.py)
# ---------------------------------------------------------------------------
# CLAHE (Contrast Limited Adaptive Histogram Equalization):
#   Spot Ä±ÅÄ±k / parlak zemin yansÄ±malarÄ±nÄ± normalize eder.
#   clipLimit: 1.0 = kapalÄ±  |  2.5 = dengeli  |  4.0 = gÃ¼Ã§lÃ¼ (gÃ¼rÃ¼ltÃ¼ artar)
CLAHE_CLIP_LIMIT      = 2.5   # CLAHE kontrast sÄ±nÄ±rÄ±
CLAHE_TILE_SIZE       = 8     # CLAHE kutucuk boyutu (piksel, 8 = Ã¶nerilen)

# SÃ¼tun sÃ¼rekliliÄi aÄÄ±rlÄ±ÄÄ±:
#   KuÅ bakÄ±ÅÄ± gÃ¶rÃ¼ntÃ¼sÃ¼nde bir sÃ¼tun ancak LANE_CONTINUITY_RATIO * yÃ¼kseklik kadar
#   beyaz piksel iÃ§eriyorsa tam aÄÄ±rlÄ±k alÄ±r; daha azsa aÄÄ±rlÄ±k orantÄ±lÄ± dÃ¼ÅÃ¼rÃ¼lÃ¼r.
#   Åerit Ã§izgileri dikey yÃ¶nde sÃ¼rekli â yÃ¼ksek aÄÄ±rlÄ±k.
#   Noktasal yansÄ±malar â dÃ¼ÅÃ¼k aÄÄ±rlÄ±k â histogram'dan baskÄ±lanÄ±r.
LANE_CONTINUITY_RATIO = 0.15  # [0.0â0.5]; dÃ¼ÅÃ¼k = daha permissif

# ---------------------------------------------------------------------------
# Ãift bÃ¶lge Åerit takibi (yakÄ±n / uzak aÄÄ±rlÄ±klÄ± hata)
# ---------------------------------------------------------------------------
# KuÅ bakÄ±ÅÄ± dikey olarak Ã¼Ã§ bÃ¶lgeye ayrÄ±lÄ±r:
#   Ãst  LANE_FAR_RATIO   â uzak gÃ¶rÃ¼Å  : dÃ¶nÃ¼Å tahmini (look-ahead)
#   Orta                  â kullanÄ±lmaz
#   Alt  LANE_NEAR_RATIO  â yakÄ±n gÃ¶rÃ¼Å : anlÄ±k yanal konum / ortalama
#
# Nihai hata = LANE_NEAR_WEIGHT Ã yakÄ±n_hata + LANE_FAR_WEIGHT Ã uzak_hata
# ToplamlarÄ± 1.0 olmasÄ± gerekmez; eksik bÃ¶lge varsa diÄeri tek baÅÄ±na kullanÄ±lÄ±r.
LANE_FAR_RATIO   = 0.35   # KuÅ bakÄ±ÅÄ±nÄ±n Ã¼st bu oranÄ± = uzak gÃ¶rÃ¼Å
LANE_NEAR_RATIO  = 0.40   # KuÅ bakÄ±ÅÄ±nÄ±n alt bu oranÄ± = yakÄ±n gÃ¶rÃ¼Å
LANE_FAR_WEIGHT  = 0.60   # Uzak hata aÄÄ±rlÄ±ÄÄ±  (dÃ¶nÃ¼Å Ã¶ngÃ¶rÃ¼sÃ¼)
LANE_NEAR_WEIGHT = 0.40   # YakÄ±n hata aÄÄ±rlÄ±ÄÄ± (anlÄ±k ortalama)
