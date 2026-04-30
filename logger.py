# =============================================================================
# logger.py  —  Gerçek zamanlı hata kayıt sistemi (CSV + stabilite raporu)
# =============================================================================
import csv
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from config import LOG_DURATION_SEC, LOG_FILE


class ErrorLogger:
    """Sürüş sırasında yanal piksel hatalarını kaydeder, stabilite raporu üretir.

    Kullanım
    --------
    logger = ErrorLogger()
    while calisıyor:
        logger.update(error)   # kayıp şerit kareler için None geçin
    logger.finish()            # süre dolmadan önce de dışa aktarır
    """

    def __init__(
        self,
        duration_sec: float = LOG_DURATION_SEC,
        export_file: str    = LOG_FILE,
    ):
        self.duration    = duration_sec
        self.export_file = Path(export_file)
        self.start_time  = time.time()
        self.finished    = False

        self._errors:     list = []
        self._timestamps: list = []
        self._lost:       int  = 0

    # ------------------------------------------------------------------
    def update(self, error) -> None:
        """Bir karenin hata değerini kaydeder. Kayıp şerit için None geçin."""
        if self.finished:
            return
        now = time.time()
        if error is None:
            self._lost += 1
            error = 0.0
        self._errors.append(float(error))
        self._timestamps.append(now - self.start_time)
        if now - self.start_time >= self.duration:
            self.finish()

    # ------------------------------------------------------------------
    def finish(self) -> None:
        """Kayıt işlemini sonlandır, raporu yazdır, CSV'e aktar."""
        if self.finished:
            return
        self.finished = True
        self._report()
        self._export_csv()

    # main.py'den logger.close() cagrisi icin alias
    close = finish

    # ------------------------------------------------------------------
    def _report(self) -> None:
        if not self._errors:
            print("[Logger] Veri toplanamadı.")
            return
        arr      = np.array(self._errors)
        total    = len(arr)
        run_secs = self._timestamps[-1] if self._timestamps else 0
        fps_avg  = total / run_secs if run_secs > 0 else 0
        lost_pct = 100.0 * self._lost / total if total else 0.0

        print()
        print("======================================")
        print("       ŞERİT TAKİP STABİLİTE RAPORU  ")
        print("======================================")
        print(f"  Tarih/saat   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Süre         : {run_secs:.1f} s")
        print(f"  Kare sayısı  : {total}  ({fps_avg:.1f} fps ortalama)")
        print(f"  Kayıp şerit  : {self._lost} kare  ({lost_pct:.1f} %)")
        print(f"  Ortalama hata: {np.mean(arr):+.2f} px  (sapma)")
        print(f"  Std sapma    : {np.std(arr):.2f} px")
        print(f"  Maks |hata|  : {np.max(np.abs(arr)):.2f} px")
        print(f"  CSV kaydedil : {self.export_file}")
        print("======================================")
        print()

    # ------------------------------------------------------------------
    def _export_csv(self) -> None:
        with open(self.export_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["kare", "zaman_s", "hata_px"])
            for i, (t, e) in enumerate(zip(self._timestamps, self._errors)):
                writer.writerow([i, f"{t:.4f}", f"{e:.1f}"])


# =============================================================================
# DiagLogger — kapsamlı per-frame tanı kaydı
# =============================================================================
class DiagLogger:
    """Surus sirasinda her frame'in detayli durumunu CSV'ye yazar.

    Onceki errror logger'dan farkli olarak: error + lane_center + peaks +
    motor + state + fps tum bilgiler tek satirda.

    Cikti: diag_<TIMESTAMP>.csv (her run ayri dosya)

    Kullanim:
        diag = DiagLogger()
        diag.log(frame_idx, error=..., lane_center=..., left_x=..., ...)
        diag.close()
    """

    HEADERS = [
        "frame", "t_sec", "fps",
        "state", "light", "sign",
        "error", "lane_center", "near_left", "near_right",
        "far_left", "far_right",
        "mask_white_pct", "v_mean",
        "left_speed", "right_speed", "correction",
        "lost_frames",
        "events",  # crosswalk, hemzemin, vs.
    ]

    def __init__(self, log_dir: str = "."):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = Path(log_dir) / f"diag_{ts}.csv"
        self._file = open(self.path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(self.HEADERS)
        self._file.flush()
        self._start = time.time()
        self._last_flush = self._start
        self._frame_count = 0
        print(f"[diag] Kaydediyor: {self.path}")

    def log(self, **kwargs) -> None:
        """Bir frame'lik tani kaydi. Eksik field'lar bos kalir."""
        self._frame_count += 1
        now = time.time()
        elapsed = now - self._start
        fps = self._frame_count / elapsed if elapsed > 0 else 0.0

        row = [
            kwargs.get("frame", self._frame_count),
            f"{elapsed:.3f}",
            f"{fps:.1f}",
            kwargs.get("state", ""),
            kwargs.get("light", ""),
            kwargs.get("sign", ""),
            self._fmt(kwargs.get("error")),
            self._fmt(kwargs.get("lane_center")),
            self._fmt(kwargs.get("near_left")),
            self._fmt(kwargs.get("near_right")),
            self._fmt(kwargs.get("far_left")),
            self._fmt(kwargs.get("far_right")),
            self._fmt(kwargs.get("mask_white_pct"), fmt="{:.1f}"),
            self._fmt(kwargs.get("v_mean"), fmt="{:.1f}"),
            self._fmt(kwargs.get("left_speed"), fmt="{:.1f}"),
            self._fmt(kwargs.get("right_speed"), fmt="{:.1f}"),
            self._fmt(kwargs.get("correction"), fmt="{:.2f}"),
            kwargs.get("lost_frames", ""),
            kwargs.get("events", ""),
        ]
        self._writer.writerow(row)

        # Her saniyede bir flush et (crash'te veri kaybetme)
        if now - self._last_flush > 1.0:
            self._file.flush()
            self._last_flush = now

    @staticmethod
    def _fmt(v, fmt: str = "{}"):
        if v is None:
            return ""
        try:
            return fmt.format(v)
        except (ValueError, TypeError):
            return str(v)

    def close(self):
        try:
            self._file.flush()
            self._file.close()
            print(f"[diag] Kapatildi ({self._frame_count} kare): {self.path}")
        except Exception:
            pass