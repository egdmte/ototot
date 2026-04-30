
# =============================================================================
# frame_logger.py  —  Yarış sırası kare ve durum kaydedici (replay/debug)
#
# Her N karede bir:
#   - Debug görüntüsü → JPEG
#   - Hata, motor komutları, FPS → CSV
#
# Yarış sonrası ihtiyaca göre çevrimdışı analiz yapılır.
# =============================================================================
import csv
import os
import time
from pathlib import Path

import cv2
import numpy as np

from config import (
    FRAME_LOG_ENABLED, FRAME_LOG_DIR,
    FRAME_LOG_INTERVAL, FRAME_LOG_JPEG_Q,
)


class FrameLogger:
    """Replay için debug karelerini ve metaverileri kaydeder."""

    def __init__(self, enabled: bool = FRAME_LOG_ENABLED):
        self.enabled  = enabled
        self.frame_id = 0
        self.saved    = 0
        self.session_dir: Path | None = None
        self._csv_file = None
        self._csv_writer = None

        if not self.enabled:
            return

        ts = time.strftime("%Y%m%d_%H%M%S")
        self.session_dir = Path(FRAME_LOG_DIR) / ts
        self.session_dir.mkdir(parents=True, exist_ok=True)

        csv_path = self.session_dir / "telemetri.csv"
        self._csv_file = open(csv_path, "w", newline="", encoding="utf-8")
        self._csv_writer = csv.writer(self._csv_file)
        self._csv_writer.writerow([
            "kare_id", "zaman_s", "fps",
            "hata", "sol_pwm", "sag_pwm",
            "durum", "kayit_dosya",
        ])
        self._t0 = time.time()
        print(f"[frame_logger] Aktif → {self.session_dir}")

    # ------------------------------------------------------------------
    def log(self, debug_frame: np.ndarray | None,
            error, left_pwm: float, right_pwm: float,
            fps: float, status: str = "") -> None:
        """Bir kareyi (her FRAME_LOG_INTERVAL'da bir) kaydet."""
        if not self.enabled:
            return
        self.frame_id += 1
        if self.frame_id % FRAME_LOG_INTERVAL != 0:
            return

        rel_path = ""
        if debug_frame is not None and self.session_dir is not None:
            fname = f"f_{self.frame_id:06d}.jpg"
            full = self.session_dir / fname
            try:
                bgr = cv2.cvtColor(debug_frame, cv2.COLOR_RGB2BGR)
                cv2.imwrite(str(full), bgr,
                            [cv2.IMWRITE_JPEG_QUALITY, FRAME_LOG_JPEG_Q])
                rel_path = fname
                self.saved += 1
            except Exception as e:
                print(f"[frame_logger] Kayıt hatası: {e}")

        if self._csv_writer is not None:
            err_v = "" if error is None else f"{float(error):.1f}"
            self._csv_writer.writerow([
                self.frame_id,
                f"{time.time() - self._t0:.3f}",
                f"{fps:.1f}",
                err_v,
                f"{left_pwm:.1f}",
                f"{right_pwm:.1f}",
                status,
                rel_path,
            ])

    # ------------------------------------------------------------------
    def close(self) -> None:
        if self._csv_file is not None:
            try:
                self._csv_file.close()
            except Exception:
                pass
            self._csv_file = None
        if self.enabled:
            print(f"[frame_logger] Kaydedildi: {self.saved} kare → {self.session_dir}")
