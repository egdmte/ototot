#!/usr/bin/env python3
"""
tune.py  —  Yarış günü canlı parametre ayar aracı
            (18. MEB Uluslararası Robot Yarışması 2026)

Kullanım:
    python tune.py

Modlar (M ile geç):
    0  Şerit Önizleme  — bird-eye + maske + hata görüntüsü
    1  HSV Ayar        — beyaz şerit eşiklerini canlı ayarla
    2  PD + Hız        — KP, KD, BASE_SPEED, MIN/MAX_SPEED
    3  Şerit Detay     — MIN_LANE_SIGNAL, hafıza, CLAHE
    4  Perspektif      — PERSP_SRC köşelerini mouse ile sürükle

Tuşlar (mod 0-3):
    TAB / Shift+TAB   : Sonraki / önceki parametre
    ↑ / ↓             : ±1 (ya da ±0.01 kesirli değerlerde)
    PageUp / PageDown  : ±10 (ya da ±0.1 kesirli değerlerde)
    S                  : config.py'ye kaydet
    R                  : config.py'den yeniden yükle
    M                  : Mod değiştir
    Q / Esc            : Çık

Perspektif modunda (mod 4):
    Sol tıkla sürükle  : Köşe taşı
    S                  : config.py'ye kaydet (PERSP_SRC)
    M / Q              : Çık
"""

import os
import re
import sys
import time

import cv2
import numpy as np

# ─── Kamera ───────────────────────────────────────────────────────────────────
try:
    from picamera2 import Picamera2
    _USE_PI = True
except ImportError:
    _USE_PI = False

try:
    from config import CAMERA_ROTATE_180 as _ROTATE_180
except ImportError:
    _ROTATE_180 = False

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.py')

# ─── Config okuyucu / yazıcı ──────────────────────────────────────────────────

def _read_cfg(key, default=None):
    """config.py'den bir parametrenin değerini oku."""
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                m = re.match(rf'^\s*{re.escape(key)}\s*=\s*([^\n#]+)', line)
                if m:
                    return eval(m.group(1).strip())
    except Exception:
        pass
    return default


def _write_cfg(key, value):
    """config.py'deki bir parametrenin değerini güncelle."""
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
        # Satır sonundaki yorumu koruyarak sadece değeri değiştir
        pattern = rf'^({re.escape(key)}\s*=\s*)([^\n#]*)([ \t]*#[^\n]*)?'
        def replacer(m):
            comment = m.group(3) or ''
            return f"{m.group(1)}{repr(value)}{comment}"
        new_content = re.sub(pattern, replacer, content,
                              flags=re.MULTILINE, count=1)
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    except Exception as e:
        print(f"[tune] Kayıt hatası ({key}): {e}")
        return False


# ─── Parametre sınıfı ─────────────────────────────────────────────────────────

class Param:
    """Tek bir config.py parametresini temsil eder.

    tuple_idx  : None → scalar  |  int → tuple içindeki indeks
    step       : ↑/↓ adımı
    big_step   : PageUp/PageDown adımı
    lo / hi    : izin verilen aralık
    """

    def __init__(self, label, key, tuple_idx=None,
                 step=1, big_step=None, lo=0, hi=255):
        self.label     = label
        self.key       = key
        self.tuple_idx = tuple_idx
        self.step      = step
        self.big_step  = big_step if big_step is not None else step * 10
        self.lo        = lo
        self.hi        = hi
        self._val      = None   # yüklendiğinde set edilir

    @property
    def value(self):
        if self._val is None:
            self.reload()
        return self._val

    @value.setter
    def value(self, v):
        if isinstance(v, float) or isinstance(self.step, float):
            v = round(float(v), 4)
        else:
            v = int(v)
        self._val = max(self.lo, min(self.hi, v))

    def reload(self):
        raw = _read_cfg(self.key)
        if raw is None:
            return
        if self.tuple_idx is not None:
            self._val = raw[self.tuple_idx]
        else:
            self._val = raw

    def save(self):
        if self.tuple_idx is not None:
            full = list(_read_cfg(self.key, (0,) * (self.tuple_idx + 1)))
            full[self.tuple_idx] = self._val
            _write_cfg(self.key, tuple(full))
        else:
            _write_cfg(self.key, self._val)

    def inc(self, big=False):
        self.value = self._val + (self.big_step if big else self.step)

    def dec(self, big=False):
        self.value = self._val - (self.big_step if big else self.step)

    def fmt(self):
        if isinstance(self.step, float):
            return f"{self._val:.3f}"
        return str(self._val)


# ─── Parametre grupları ───────────────────────────────────────────────────────

def _build_params():
    return {
        'HSV': [
            Param('V_min  Normal ',  'WHITE_HSV_LOW_NORMAL',  2, step=1,    big_step=10, lo=0,   hi=255),
            Param('S_max  Normal ',  'WHITE_HSV_HIGH_NORMAL', 1, step=1,    big_step=10, lo=0,   hi=255),
            Param('V_min  Karanlik', 'WHITE_HSV_LOW_DARK',    2, step=1,    big_step=10, lo=0,   hi=255),
            Param('S_max  Karanlik', 'WHITE_HSV_HIGH_DARK',   1, step=1,    big_step=10, lo=0,   hi=255),
            Param('V_min  Parlak  ', 'WHITE_HSV_LOW_BRIGHT',  2, step=1,    big_step=10, lo=0,   hi=255),
            Param('S_max  Parlak  ', 'WHITE_HSV_HIGH_BRIGHT', 1, step=1,    big_step=10, lo=0,   hi=255),
        ],
        'PD': [
            Param('KP           ',  'KP',         step=0.01, big_step=0.1, lo=0.0, hi=5.0),
            Param('KD           ',  'KD',         step=0.01, big_step=0.1, lo=0.0, hi=5.0),
            Param('Base Hiz     ',  'BASE_SPEED', step=1,    big_step=5,   lo=10,  hi=100),
            Param('Min  Hiz     ',  'MIN_SPEED',  step=1,    big_step=5,   lo=5,   hi=80),
            Param('Max  Hiz     ',  'MAX_SPEED',  step=1,    big_step=5,   lo=20,  hi=100),
            Param('K_speed      ',  'K_SPEED',    step=0.01, big_step=0.05, lo=0.0, hi=2.0),
        ],
        'SERIT': [
            Param('Min Sinyal   ',  'MIN_LANE_SIGNAL',      step=10,  big_step=50,  lo=10,  hi=5000),
            Param('Hafiza(kare) ',  'LANE_MEMORY_FRAMES',   step=1,   big_step=5,   lo=0,   hi=60),
            Param('Arama Pencere',  'LANE_SEARCH_WINDOW',   step=5,   big_step=20,  lo=10,  hi=320),
            Param('Tahmini Genls',  'ASSUMED_LANE_WIDTH',   step=5,   big_step=20,  lo=50,  hi=640),
            Param('CLAHE Clip   ',  'CLAHE_CLIP_LIMIT',     step=0.1, big_step=0.5, lo=0.5, hi=8.0),
            Param('Sureklilik   ',  'LANE_CONTINUITY_RATIO',step=0.01,big_step=0.05,lo=0.0, hi=0.5),
            Param('Uzak Oran    ',  'LANE_FAR_RATIO',       step=0.01,big_step=0.05,lo=0.0, hi=0.6),
            Param('Yakin Oran   ',  'LANE_NEAR_RATIO',      step=0.01,big_step=0.05,lo=0.0, hi=0.6),
            Param('Uzak Agirlik ',  'LANE_FAR_WEIGHT',      step=0.01,big_step=0.05,lo=0.0, hi=1.0),
            Param('Yakin Agirlik',  'LANE_NEAR_WEIGHT',     step=0.01,big_step=0.05,lo=0.0, hi=1.0),
        ],
    }


# ─── Kamera sarmalayıcı ───────────────────────────────────────────────────────

class _Camera:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        if _USE_PI:
            self._pi = Picamera2()
            cfg = self._pi.create_preview_configuration(
                main={"format": "RGB888", "size": (w, h)},
                buffer_count=4,          # starvation önleme
            )
            self._pi.configure(cfg)
            self._pi.start()
            time.sleep(1)
            self._mode = 'pi'
        else:
            self._cv = cv2.VideoCapture(0)
            self._cv.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            self._cv.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            self._mode = 'cv'

    def read_bgr(self):
        if self._mode == 'pi':
            frame = self._pi.capture_array()
            # Pi 5 / yeni libcamera: RGB888 bazen XRGB8888 (4 kanal) gelir
            if frame.ndim == 3 and frame.shape[2] == 4:
                frame = frame[:, :, :3]
            frame = cv2.cvtColor(frame.copy(), cv2.COLOR_RGB2BGR)
        else:
            ret, frame = self._cv.read()
            if not ret:
                return np.zeros((self.h, self.w, 3), dtype=np.uint8)
            frame = cv2.resize(frame, (self.w, self.h))
        if _ROTATE_180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        return frame

    def stop(self):
        if self._mode == 'pi':
            self._pi.stop()
        else:
            self._cv.release()


# ─── Görüntü işleme (tune.py kendi pipeline'ı) ───────────────────────────────

class _Processor:
    """config.py'deki güncel değerlerle şerit tespiti yapar."""

    def __init__(self, w, h):
        self.w = w
        self.h = h
        self._reload()

    def _reload(self):
        from config import (
            ROI_TOP_RATIO, PERSP_SRC,
            WHITE_HSV_LOW_DARK, WHITE_HSV_HIGH_DARK,
            WHITE_HSV_LOW_NORMAL, WHITE_HSV_HIGH_NORMAL,
            WHITE_HSV_LOW_BRIGHT, WHITE_HSV_HIGH_BRIGHT,
            MIN_LANE_SIGNAL, ASSUMED_LANE_WIDTH,
            LANE_CONTINUITY_RATIO, CLAHE_CLIP_LIMIT, CLAHE_TILE_SIZE,
            LANE_FAR_RATIO, LANE_NEAR_RATIO, LANE_FAR_WEIGHT, LANE_NEAR_WEIGHT,
        )
        self.bird_h = int(self.h * (1.0 - ROI_TOP_RATIO))
        src = np.float32(PERSP_SRC)
        dst = np.float32([
            [0,       0],
            [self.w,  0],
            [0,       self.bird_h],
            [self.w,  self.bird_h],
        ])
        self.M = cv2.getPerspectiveTransform(src, dst)
        self._thresholds = {
            'dark':   (WHITE_HSV_LOW_DARK,   WHITE_HSV_HIGH_DARK),
            'normal': (WHITE_HSV_LOW_NORMAL, WHITE_HSV_HIGH_NORMAL),
            'bright': (WHITE_HSV_LOW_BRIGHT, WHITE_HSV_HIGH_BRIGHT),
        }
        self._min_signal   = MIN_LANE_SIGNAL
        self._lane_w       = ASSUMED_LANE_WIDTH
        self._cont_ratio   = LANE_CONTINUITY_RATIO
        self._far_ratio    = LANE_FAR_RATIO
        self._near_ratio   = LANE_NEAR_RATIO
        self._far_weight   = LANE_FAR_WEIGHT
        self._near_weight  = LANE_NEAR_WEIGHT
        self._clahe        = cv2.createCLAHE(
            clipLimit=CLAHE_CLIP_LIMIT,
            tileGridSize=(int(CLAHE_TILE_SIZE), int(CLAHE_TILE_SIZE)),
        )
        self._kern = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))

    def process(self, bgr_frame, persp_pts=None):
        """BGR kareyi işler.

        Returns
        -------
        bird_bgr   : kuş bakışı BGR (debug için)
        mask       : ikili maske (uint8)
        error      : int | None
        v_mean     : float
        left_col   : int | None
        right_col  : int | None
        """
        if persp_pts is not None:
            src = np.float32(persp_pts)
            dst = np.float32([
                [0,      0],
                [self.w, 0],
                [0,      self.bird_h],
                [self.w, self.bird_h],
            ])
            M = cv2.getPerspectiveTransform(src, dst)
        else:
            M = self.M

        bird = cv2.warpPerspective(bgr_frame, M, (self.w, self.bird_h))
        bird_rgb = cv2.cvtColor(bird, cv2.COLOR_BGR2RGB)

        # CLAHE
        lab = cv2.cvtColor(bird_rgb, cv2.COLOR_RGB2LAB)
        l, a, b = cv2.split(lab)
        l_eq = self._clahe.apply(l)
        bird_proc = cv2.cvtColor(cv2.merge([l_eq, a, b]), cv2.COLOR_LAB2RGB)

        hsv    = cv2.cvtColor(bird_proc, cv2.COLOR_RGB2HSV)
        v_mean = float(np.mean(hsv[:, :, 2]))

        if v_mean < 100:
            lo, hi = self._thresholds['dark']
        elif v_mean > 200:
            lo, hi = self._thresholds['bright']
        else:
            lo, hi = self._thresholds['normal']

        mask = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  self._kern)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._kern)

        # Sütun sürekliliği
        col_cov = (mask > 0).sum(axis=0).astype(np.float32)
        min_cov = max(float(self.bird_h) * self._cont_ratio, 1.0)
        cont_w  = np.minimum(col_cov / min_cov, 1.0)

        mid = self.w // 2

        # Yakın / uzak dilim histogramları
        near_rows  = int(self.bird_h * self._near_ratio)
        far_rows   = int(self.bird_h * self._far_ratio)
        near_start = self.bird_h - near_rows

        def _slice_hist(m):
            h = np.sum(m, axis=0).astype(np.float32) * cont_w
            return cv2.GaussianBlur(h.reshape(1, -1), (1, 31), 0).flatten()

        near_hist = _slice_hist(mask[near_start:])
        far_hist  = _slice_hist(mask[:far_rows])

        def _peak(hist_arr, lo_x, hi_x):
            region = hist_arr[lo_x:hi_x]
            total  = float(region.sum())
            if total < self._min_signal:
                return None
            return int(np.average(np.arange(lo_x, hi_x), weights=region))

        near_lp = _peak(near_hist, 0,   mid)
        near_rp = _peak(near_hist, mid, self.w)
        far_lp  = _peak(far_hist,  0,   mid)
        far_rp  = _peak(far_hist,  mid, self.w)

        def _center(lp, rp):
            if lp is not None and rp is not None: return (lp + rp) // 2
            elif lp is not None:                  return lp + self._lane_w // 2
            elif rp is not None:                  return rp - self._lane_w // 2
            return None

        near_c = _center(near_lp, near_rp)
        far_c  = _center(far_lp,  far_rp)

        if near_c is None and far_c is None:
            bird_bgr = cv2.cvtColor(bird_proc, cv2.COLOR_RGB2BGR)
            return bird_bgr, mask, None, v_mean, None, None, None, None

        if near_c is None:
            error = mid - int(far_c)
        elif far_c is None:
            error = mid - int(near_c)
        else:
            error = int(self._near_weight * (mid - near_c)
                       + self._far_weight  * (mid - far_c))

        bird_bgr = cv2.cvtColor(bird_proc, cv2.COLOR_RGB2BGR)
        return bird_bgr, mask, error, v_mean, near_lp, near_rp, far_lp, far_rp


# ─── Bilgi paneli çizici ──────────────────────────────────────────────────────

_MODE_NAMES = ['Serit Onizleme', 'HSV Ayar', 'PD + Hiz', 'Serit Detay', 'Perspektif']
_PANEL_W    = 300
_TXT_SCALE  = 0.42
_TXT_THICK  = 1


def _txt(img, text, pos, color=(220, 220, 220), bold=False):
    cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX,
                _TXT_SCALE, color, 2 if bold else _TXT_THICK, cv2.LINE_AA)


def _draw_panel(height, mode_idx, mode_name, params, sel_idx, status_lines):
    panel = np.zeros((height, _PANEL_W, 3), dtype=np.uint8)
    panel[:] = (30, 30, 30)

    y = 18
    # Başlık
    _txt(panel, 'TUNE v1.0 -- MEB 2026', (6, y), (0, 200, 255), bold=True); y += 20
    cv2.line(panel, (0, y), (_PANEL_W, y), (80, 80, 80), 1); y += 8

    # Mod
    _txt(panel, f'MOD [{mode_idx}]: {mode_name}', (6, y), (100, 255, 100)); y += 18
    cv2.line(panel, (0, y), (_PANEL_W, y), (60, 60, 60), 1); y += 8

    # Tuş kılavuzu
    for hint in ['TAB: param sec', 'Yukari/Asagi: +-1', 'PgUp/Dn: +-10',
                 'S: kaydet  R: yukle', 'M: mod  Q: cik']:
        _txt(panel, hint, (6, y), (140, 140, 140)); y += 15
    cv2.line(panel, (0, y), (_PANEL_W, y), (60, 60, 60), 1); y += 8

    # Parametreler
    if params:
        _txt(panel, 'PARAMETRELER:', (6, y), (200, 200, 0)); y += 16
        for i, p in enumerate(params):
            active = (i == sel_idx)
            mark   = '>' if active else ' '
            col    = (0, 255, 255) if active else (200, 200, 200)
            bg_col = (60, 40, 0)  if active else (30, 30, 30)
            # Arka plan vurgusu
            cv2.rectangle(panel, (0, y - 13), (_PANEL_W, y + 3), bg_col, -1)
            _txt(panel, f'{mark} {p.label}: {p.fmt()}', (6, y), col, bold=active)
            y += 17
        cv2.line(panel, (0, y), (_PANEL_W, y), (60, 60, 60), 1); y += 8
    else:
        # Perspektif modu
        _txt(panel, 'PERSPEKTIF MODU:', (6, y), (200, 200, 0)); y += 16
        _txt(panel, 'Sol tikla sürükle', (6, y), (200, 200, 200)); y += 15
        _txt(panel, 'S = kaydet', (6, y), (200, 200, 200)); y += 15
        cv2.line(panel, (0, y), (_PANEL_W, y), (60, 60, 60), 1); y += 8

    # Durum satırları
    _txt(panel, 'DURUM:', (6, y), (200, 200, 0)); y += 16
    for line in status_lines:
        _txt(panel, line, (6, y)); y += 15

    return panel


# ─── Perspektif modu yardımcıları ────────────────────────────────────────────

_PT_R = 8
_PT_COL  = (0, 255, 0)
_PT_SEL  = (0, 0, 255)
_LN_COL  = (255, 200, 0)


def _draw_persp_overlay(frame, pts, selected):
    vis   = frame.copy()
    order = [0, 1, 3, 2, 0]
    for i in range(len(order) - 1):
        cv2.line(vis, tuple(pts[order[i]]), tuple(pts[order[i+1]]), _LN_COL, 1)
    for i, (x, y) in enumerate(pts):
        col = _PT_SEL if i == selected else _PT_COL
        cv2.circle(vis, (x, y), _PT_R, col, -1)
        cv2.putText(vis, str(i), (x + 10, y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1)
    cv2.putText(vis, '0=sol-ust  1=sag-ust  2=sol-alt  3=sag-alt',
                (6, vis.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX,
                0.4, (200, 200, 200), 1)
    return vis


# ─── Ana uygulama ─────────────────────────────────────────────────────────────

def main():
    from config import WIDTH, HEIGHT

    print()
    print("=" * 56)
    print("  TUNE v1.0  —  MEB 2026 Otonom Arac Ayar Araci")
    print("=" * 56)
    print(f"  Kamera: {'Picamera2 (Pi)' if _USE_PI else 'USB / VideoCapture'}")
    print(f"  Config: {CONFIG_PATH}")
    print()
    print("  Pencere aciliyor...  (q / Esc = cik)")
    print()

    cam  = _Camera(WIDTH, HEIGHT)
    proc = _Processor(WIDTH, HEIGHT)

    # Parametre grupları
    all_params = _build_params()
    for grp in all_params.values():
        for p in grp:
            p.reload()

    MODE_PARAM_KEYS = [None, 'HSV', 'PD', 'SERIT', None]  # indeks → grup adı

    mode        = 0
    sel_idx     = 0
    saved_msg   = ''
    saved_until = 0.0
    fps_t       = time.time()
    fps_count   = 0
    fps_val     = 0.0

    # Perspektif durumu
    persp_pts      = [list(p) for p in _read_cfg('PERSP_SRC',
                        [[160, 300], [480, 300], [0, 480], [640, 480]])]
    persp_sel      = -1
    persp_dragging = False
    persp_use      = False   # True → proc'a persp_pts geçir

    WINNAME = 'Otonom Arac Tune'
    cv2.namedWindow(WINNAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINNAME, WIDTH + _PANEL_W, HEIGHT)

    # Mouse callback (perspektif modu için)
    def on_mouse(event, x, y, flags, param):
        nonlocal persp_sel, persp_dragging
        # Sadece perspektif modunda ve kamera bölgesinde (x < WIDTH) aktif
        if mode != 4 or x >= WIDTH:
            return
        if event == cv2.EVENT_LBUTTONDOWN:
            dists = [abs(x - p[0]) + abs(y - p[1]) for p in persp_pts]
            idx   = int(np.argmin(dists))
            if dists[idx] < _PT_R * 3:
                persp_sel      = idx
                persp_dragging = True
        elif event == cv2.EVENT_MOUSEMOVE and persp_dragging:
            persp_pts[persp_sel] = [
                int(np.clip(x, 0, WIDTH - 1)),
                int(np.clip(y, 0, HEIGHT - 1)),
            ]
        elif event == cv2.EVENT_LBUTTONUP:
            persp_dragging = False

    cv2.setMouseCallback(WINNAME, on_mouse)

    def current_params():
        key = MODE_PARAM_KEYS[mode]
        return all_params.get(key, []) if key else []

    def _update_proc_persp(pts):
        """persp_pts değiştiğinde proc.M'i anında senkronize eder."""
        src = np.float32(pts)
        dst = np.float32([
            [0,      0],
            [proc.w, 0],
            [0,      proc.bird_h],
            [proc.w, proc.bird_h],
        ])
        proc.M = cv2.getPerspectiveTransform(src, dst)

    def save_all():
        nonlocal saved_msg, saved_until
        key = MODE_PARAM_KEYS[mode]
        if key:
            for p in all_params[key]:
                p.save()
            saved_msg   = f'Kaydedildi: {key}'
        elif mode == 4:
            _write_cfg('PERSP_SRC', [list(p) for p in persp_pts])
            saved_msg = 'PERSP_SRC kaydedildi'
            # proc.M'i hemen güncelle — mode 0 artık aynı perspektifi kullanır
            _update_proc_persp(persp_pts)
        saved_until = time.time() + 2.5
        print(f'[tune] {saved_msg}')

    def reload_all():
        key = MODE_PARAM_KEYS[mode]
        if key:
            for p in all_params[key]:
                p.reload()
            # Processor'ı da güncelle
            proc._reload()
        elif mode == 4:
            nonlocal persp_pts
            persp_pts = [list(p) for p in _read_cfg('PERSP_SRC',
                            [[160, 300], [480, 300], [0, 480], [640, 480]])]
            _update_proc_persp(persp_pts)
        print(f'[tune] Yeniden yuklendi')

    try:
        while True:
            bgr = cam.read_bgr()

            # FPS hesapla
            fps_count += 1
            now = time.time()
            if now - fps_t >= 1.0:
                fps_val   = fps_count / (now - fps_t)
                fps_count = 0
                fps_t     = now

            # --- Görüntü işleme ---
            pts_arg = persp_pts if (mode == 4 and persp_use) else None
            bird, mask, error, v_mean, lp, rp, far_lp, far_rp = proc.process(bgr, pts_arg)

            # --- Sol panel (kamera / bird-eye / perspektif) ---
            if mode == 0:
                # Şerit önizleme: kuş bakışı + maske overlay + hata çizgisi
                vis = bird.copy()
                mask_c = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
                vis = cv2.addWeighted(vis, 0.65, mask_c, 0.35, 0)
                mid = WIDTH // 2
                h_b   = bird.shape[0]
                far_h = int(h_b * _read_cfg('LANE_FAR_RATIO', 0.35))
                if lp is not None:
                    cv2.line(vis, (lp, 0), (lp, h_b), (0, 220, 0), 2)
                if rp is not None:
                    cv2.line(vis, (rp, 0), (rp, h_b), (0, 220, 0), 2)
                # Uzak görüş çizgileri — cyan, üst bölgede
                if far_lp is not None:
                    cv2.line(vis, (far_lp, 0), (far_lp, far_h), (220, 200, 0), 1)
                if far_rp is not None:
                    cv2.line(vis, (far_rp, 0), (far_rp, far_h), (220, 200, 0), 1)
                if error is not None:
                    cx = mid - error
                    cv2.line(vis, (cx,  0), (cx,  h_b), (0, 100, 255), 2)
                cv2.line(vis, (mid, 0), (mid, h_b), (80, 80, 255), 1)
                # Kamera görüntüsüyle birleştir (üst = raw, alt = bird-eye)
                raw_h = HEIGHT - h_b
                raw_resized = cv2.resize(bgr, (WIDTH, raw_h))
                left_panel  = np.vstack([raw_resized, vis])
            elif mode == 1:
                # HSV ayar: sol = raw, sag = maske (tam boyut)
                mask_c = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
                raw_r  = cv2.resize(bgr,    (WIDTH // 2, HEIGHT))
                mask_r = cv2.resize(mask_c, (WIDTH // 2, HEIGHT))
                left_panel = np.hstack([raw_r, mask_r])
            elif mode == 2 or mode == 3:
                # PD / Şerit: kuş bakışı tam ekran
                vis = bird.copy()
                if error is not None:
                    mid = WIDTH // 2
                    cx  = mid - error
                    cv2.line(vis, (cx, 0), (cx, bird.shape[0]), (0, 100, 255), 2)
                left_panel = cv2.resize(vis, (WIDTH, HEIGHT))
            elif mode == 4:
                # Perspektif: ham kamera + trapezoid overlay
                left_panel = _draw_persp_overlay(bgr, persp_pts,
                                                  persp_sel if persp_dragging else -1)

            # Durum bilgisi
            v_label = ('Karanlik' if v_mean < 100 else
                       'Parlak'   if v_mean > 200 else 'Normal')
            err_str = f'{error:+d}px' if error is not None else 'YOK'
            lp_str    = f'{lp}'    if lp    is not None else '-'
            rp_str    = f'{rp}'    if rp    is not None else '-'
            far_l_str = f'{far_lp}' if far_lp is not None else '-'
            far_r_str = f'{far_rp}' if far_rp is not None else '-'
            status  = [
                f'FPS:     {fps_val:.1f}',
                f'V_mean:  {v_mean:.0f} ({v_label})',
                f'Yakin S: {lp_str}px',
                f'Yakin Sa:{rp_str}px',
                f'Uzak  S: {far_l_str}px',
                f'Uzak  Sa:{far_r_str}px',
                f'Hata:    {err_str}',
            ]
            if time.time() < saved_until:
                status.append(f'>> {saved_msg}')

            # --- Sağ panel ---
            params = current_params()
            right_panel = _draw_panel(
                HEIGHT, mode, _MODE_NAMES[mode], params, sel_idx, status
            )

            # --- Birleştir ve göster ---
            if left_panel.shape[0] != HEIGHT:
                left_panel = cv2.resize(left_panel, (WIDTH, HEIGHT))
            display = np.hstack([left_panel, right_panel])
            cv2.imshow(WINNAME, display)

            # --- Tuş işleme ---
            key_code = cv2.waitKey(1) & 0xFF
            if key_code == 0xFF:
                continue

            if key_code in (ord('q'), ord('Q'), 27):   # Q veya Esc
                break

            elif key_code in (ord('m'), ord('M')):
                mode    = (mode + 1) % len(_MODE_NAMES)
                sel_idx = 0

            elif key_code == ord('s') or key_code == ord('S'):
                save_all()

            elif key_code in (ord('r'), ord('R')):
                reload_all()
                sel_idx = 0

            elif key_code == 9:   # TAB
                params = current_params()
                if params:
                    sel_idx = (sel_idx + 1) % len(params)

            elif key_code == ord('\t') or key_code == 25:   # Shift+TAB (bazı sistemlerde 25)
                params = current_params()
                if params:
                    sel_idx = (sel_idx - 1) % len(params)

            elif key_code == 82:   # ↑
                params = current_params()
                if params and sel_idx < len(params):
                    params[sel_idx].inc()

            elif key_code == 84:   # ↓
                params = current_params()
                if params and sel_idx < len(params):
                    params[sel_idx].dec()

            elif key_code == 85:   # PageUp
                params = current_params()
                if params and sel_idx < len(params):
                    params[sel_idx].inc(big=True)

            elif key_code == 86:   # PageDown
                params = current_params()
                if params and sel_idx < len(params):
                    params[sel_idx].dec(big=True)

            elif key_code == ord('+') or key_code == ord('='):
                params = current_params()
                if params and sel_idx < len(params):
                    params[sel_idx].inc()

            elif key_code == ord('-'):
                params = current_params()
                if params and sel_idx < len(params):
                    params[sel_idx].dec()

            elif key_code == ord('p') or key_code == ord('P'):
                # Perspektif modunda 'P' = kuş bakışı önizleme toggle
                if mode == 4:
                    persp_use = not persp_use

    finally:
        cam.stop()
        cv2.destroyAllWindows()

    print('[tune] Cikis yapildi.')


if __name__ == '__main__':
    main()
