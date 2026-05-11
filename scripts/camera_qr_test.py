#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 PiWallet contributors
# SPDX-License-Identifier: MIT
"""
PiWallet camera bring-up smoke test.

Continuously captures frames from a Pi Camera (Module 3 recommended) via
picamera2/libcamera, runs pyzbar QR decode on each frame, and prints any
decoded payloads. Confirms the same hardware + software path Phase 3 will
use to scan unsigned-proposal QR codes from the companion PWA.

Usage (in the piwallet venv):

    source ~/.venvs/piwallet/bin/activate
    python3 scripts/camera_qr_test.py
    python3 scripts/camera_qr_test.py --once         # single capture, then exit
    python3 scripts/camera_qr_test.py --save out.jpg # save the last frame to disk
    python3 scripts/camera_qr_test.py --size 1920x1080
"""
from __future__ import annotations

import argparse
import sys
import time

try:
    from picamera2 import Picamera2
    from libcamera import controls
except ImportError as exc:
    sys.exit(
        f"picamera2/libcamera missing: {exc}\n"
        "Install with: sudo apt install -y python3-picamera2 --no-install-recommends"
    )

try:
    from pyzbar.pyzbar import decode
except ImportError as exc:
    sys.exit(
        f"pyzbar missing: {exc}\n"
        "Install with: pip install pyzbar  (and: sudo apt install -y libzbar0t64)"
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--once", action="store_true", help="capture one frame and exit")
    p.add_argument("--size", default="1280x960", help="capture size WxH (default 1280x960)")
    p.add_argument("--save", metavar="PATH", help="save the last captured frame as JPEG")
    p.add_argument("--interval", type=float, default=0.4, help="seconds between frames (default 0.4)")
    p.add_argument(
        "--af",
        choices=["continuous", "auto", "manual"],
        default="continuous",
        help="autofocus mode (Module 3 only; ignored on fixed-focus cameras)",
    )
    return p.parse_args()


def parse_size(spec: str) -> tuple[int, int]:
    try:
        w, h = (int(x) for x in spec.lower().split("x"))
        return w, h
    except ValueError as exc:
        raise SystemExit(f"bad --size '{spec}', expected like 1280x960") from exc


def configure_af(cam: Picamera2, mode: str) -> None:
    af_map = {
        "continuous": controls.AfModeEnum.Continuous,
        "auto": controls.AfModeEnum.Auto,
        "manual": controls.AfModeEnum.Manual,
    }
    try:
        cam.set_controls({"AfMode": af_map[mode]})
    except Exception as exc:  # noqa: BLE001 - module 1/2 lack AF; not fatal
        print(f"  (AfMode={mode} not supported on this camera: {exc})")


def main() -> int:
    args = parse_args()
    width, height = parse_size(args.size)

    cam = Picamera2()
    cam.configure(cam.create_still_configuration(main={"size": (width, height)}))
    print(f"Sensor: {cam.camera_properties.get('Model', 'unknown')}")
    print(f"Capture size: {width}x{height}")

    cam.start()
    configure_af(cam, args.af)
    time.sleep(1.0)  # let AE / AF settle

    frame_no = 0
    last_frame = None
    try:
        while True:
            frame_no += 1
            last_frame = cam.capture_array("main")
            results = decode(last_frame)

            if results:
                print(f"\nframe {frame_no}: shape={last_frame.shape} - {len(results)} QR code(s):")
                for i, r in enumerate(results, 1):
                    payload_repr = r.data.decode("utf-8", errors="replace")
                    print(f"  [{i}] type={r.type} bytes={len(r.data)} payload={payload_repr!r}")
                if args.once:
                    break
            else:
                print(f"frame {frame_no}: shape={last_frame.shape} - no QR detected", end="\r")
                if args.once:
                    print()  # newline so the final status persists
                    break

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        if args.save and last_frame is not None:
            try:
                from PIL import Image
            except ImportError:
                print("\n--save requested but Pillow is not installed; skipping")
            else:
                Image.fromarray(last_frame).save(args.save)
                print(f"saved last frame to {args.save}")
        cam.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
