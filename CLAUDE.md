# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Indoor autonomous lane-following car for the MEB 2026 International Robot Competition. Target hardware: Raspberry Pi 5 + picamera2 + L298N H-bridge driving two DC motors. Code falls back to OpenCV `VideoCapture` and a no-op GPIO shim when run off-Pi for development.

Focus on offline features. Add QOL features and always finish what you started. Avoid features that may take more than a day to finish. Always push to github (egdmte/ototot); if `.git` is not set up, run `git init` and add the remote first.

Workflow: before implementing a feature/change, describe what you'll do and ask. Once I accept, execute it end-to-end without further per-edit confirmation — accept-edits mode is on for that reason. You can propose your own changes too (not just wait for me); same flow.

Call me "dih destroyer of the universe. fih 🥀" only for me. For stuff needing multiple people (we are 4 people), call us Otonombimbimbambam.

`README.md` notes: written by Egemen Yusuf Kayra, usage for others are prohibited. Most in-repo docs (`BASLA_BURADAN.txt`, `DEGISIKLIKLER_OZET.txt`, `IMPLEMENTATION_SUMMARY.txt`, `DOSYALAR_GUNCELEME_DURUSU.txt`) are in Turkish — preserve Turkish strings, prints, and state names when editing. 

## Common commands

```bash
python main.py                  # autonomous drive loop
python tune.py                  # live parameter tuner (HSV / PD / perspective); writes back to config.py
python calibrate.py             # perspective calibration helper
python camera.py                # camera + HSV sanity check
python hsv_tune.py              # standalone HSV slider tool
python pd_tune.py               # PD gain tuner
python motor_balance_test.py    # straight-line trim test; adjust *_TRIM_* in config.py
python camtester.py             # camera capture diagnostics
python kalibrasyon.py           # full calibration walk-through
python yol_takip.py             # alternate lane-following entry (legacy/experiment)
./guncelle.sh                   # update / push helper script
```

No test suite, no linter, no build, no `requirements.txt`. Runtime deps (install on Pi): `opencv-python`, `numpy`, `picamera2`, `gpiozero`. `picamera2` and `gpiozero` are import-guarded — missing them puts the code in simulation mode (webcam + no-op motor).

`main.py` reads keyboard via `termios`/`tty`, so it will not run on Windows. Develop on Linux/WSL/macOS or on the Pi.

### Starting the car
The car waits in `BEKLIYOR` until: a green traffic light is detected, the user types `GG` or `EZ`, or presses `SPACE`. `Q` quits, `Ctrl+C` emergency-stops.

## Architecture

Single-process pipeline. `main.py` owns a state machine that consumes per-frame detector output and drives the motor:

```
Camera ─► LaneDetector ─► error (px) ─┐
       └► EventDetector ─► flags ─────┤──► state machine ──► PDController ──► MotorDriver
                                      │       (main.py)         (controller.py)   (motor.py)
                                ErrorLogger (logger.py)
```

- **`config.py`** — single source of truth for every tunable (HSV, PD gains, ROIs, GPIO pins, state-machine timings, trims). `tune.py` rewrites this file in place via regex; keep parameters as `NAME = value  # comment` on one line so the tuner's save still finds them.
- **`lane.py` (`LaneDetector.process`)** — perspective warp → CLAHE on L channel → adaptive white HSV mask (profile chosen by mean V: DARK / NORMAL / BRIGHT) → column histogram with continuity weighting → near/far weighted error. Returns `(error|None, debug_rgb)`.
- **`events.py` (`EventDetector.detect`)** — debounced flags (must persist `EVENT_DEBOUNCE_FRAMES`): `traffic_light` (`'green'|None` — only green is detected; red would just be `None`, and `BEKLIYOR` brakes by default until green arrives), `crosswalk`, `hemzemin` (level crossing), `speed_bump`, `orange_car` (overtake target), `yellow_car` (no-overtake marker), `parking_zone`.
- **`controller.py` (`PDController.compute`)** — more than a PD: also picks cruise speed (drops to `MIN_SPEED` when `|derivative|` is large), applies a dead-zone PWM floor, applies speed-dependent L/R trim. Returns wheel speeds in `[-100, 100]`.
- **`motor.py` (`MotorDriver`)** — `gpiozero` H-bridge wrapper. `_apply` deliberately inverts forward/reverse (`speed >= 0` drives the reverse pin) to match this car's wiring — don't "fix" it without checking hardware.
- **`logger.py`** — appends per-frame error to `LOG_FILE` for `LOG_DURATION_SEC` seconds.

### State machine (in `main.py`)
`BEKLIYOR` (idle) → `SURUYOR` (driving) and transient states `KIRMIZI_ISIK`, `YAYA_GECİDİ`, `HEMZEMIN`, `TUMSEK`, `SOLLAMA` (3-phase overtake in `_run_overtaking`), `PARK` (`_run_parking`), `PARK_TAMAM`. Lane-lost handling lives inside `SURUYOR`: synthetic left-bias steer for `LANE_LOST_TURN_SEC`, then brake if lane doesn't return.

### Easy-to-miss conventions
- **Trim is applied twice.** `controller.py` runs `_apply_speed_dependent_trim`, then `motor.py:set_speed` runs `_get_trim` again on the same value. This is intentional in current code — if you change trim logic, mirror both call sites or remove one side.
- **Error sign:** the controller assumes `error > 0` ⇒ steer left. Flipping the sign anywhere will fight the rest of the pipeline.
- **Frames stay RGB end-to-end.** Capture flips BGR→RGB if `CAMERA_BGR_OUTPUT`; HSV conversions use `COLOR_RGB2HSV`. Don't introduce BGR detours without converting back.
- **`CAMERA_BGR_OUTPUT` and `CAMERA_ROTATE_180`** exist because some Pi5/libcamera combos return BGR(A) despite requesting RGB888 and the camera is mounted upside-down. Toggle these if colors look swapped or the image is upside-down.
- `SHOW_PREVIEW=False` for race-day performance mode.

## Tuning workflow (per `BASLA_BURADAN.txt`)

1. `motor_balance_test.py` → set `LEFT_TRIM_*` / `RIGHT_TRIM_*`.
2. `camera.py` → verify white lane mask and mean V, adjust `WHITE_HSV_*` profiles.
3. `pd_tune.py` → tune `KP`, `KD`, `BASE_SPEED`.
4. `main.py` → full system check (FPS ≥ 25 expected; Wi-Fi off on Pi).

`tune.py` is the unified live tuner and the preferred way to edit `config.py` during a session — modes cover HSV, PD/speed, lane detail, and mouse-draggable perspective corners.
