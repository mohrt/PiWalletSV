# SPDX-FileCopyrightText: PiWallet project
# SPDX-License-Identifier: MIT
"""
Minimal ST7789 test for Adafruit 1.3" bonnet (4506): only disp.fill(), no PIL image().

Use this when rgb_display_pillow_bonnet_buttons.py shows a "clean band + garbage"
pattern even after spidev.bufsiz is raised:

- If solid colors fill the WHOLE panel evenly: hardware + init are OK; the bug is
  likely in the full-frame RAMWR / PIL path (driver or Pi Zero + Blinka).
- If solid colors are STILL split / garbled: hardware, wrong SKU, seating, or SPI
  init — try Adafruit kernel installer (GETTING_STARTED stack B) or Pi Zero 2 W.

Same wiring as Adafruit bonnet demo: CE0, D25 DC, D24 RST, D26 backlight.
"""

import time

import board
from digitalio import DigitalInOut
from adafruit_rgb_display import color565, st7789

BAUDRATE = 16000000

cs_pin = DigitalInOut(board.CE0)
dc_pin = DigitalInOut(board.D25)
reset_pin = DigitalInOut(board.D24)
spi = board.SPI()
disp = st7789.ST7789(
    spi,
    height=240,
    y_offset=80,
    rotation=180,
    cs=cs_pin,
    dc=dc_pin,
    rst=reset_pin,
    baudrate=BAUDRATE,
)

backlight = DigitalInOut(board.D26)
backlight.switch_to_output()
backlight.value = True

print("Solid fill test: whole panel should flash red / green / blue. Ctrl+C to stop.")

while True:
    disp.fill(color565(255, 0, 0))
    time.sleep(0.6)
    disp.fill(color565(0, 255, 0))
    time.sleep(0.6)
    disp.fill(color565(0, 0, 255))
    time.sleep(0.6)
