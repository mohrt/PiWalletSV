# PiWallet

Air-gapped **Bitcoin SV** wallet work targeting **Raspberry Pi Zero WH** + **Adafruit 1.3" TFT bonnet** (joystick + buttons).

## Pi + bonnet bring-up

Follow **[GETTING_STARTED.md](GETTING_STARTED.md)** — short checklist: OS flash, SPI, Blinka, SPI CE tweak, copy the **repo** demo script with `scp`, run it. The guide also summarizes **Adafruit’s two official stacks** (Python vs kernel framebuffer) and how they map to product **4506**.

- Demo: [scripts/rgb_display_pillow_bonnet_buttons.py](scripts/rgb_display_pillow_bonnet_buttons.py) — Adafruit example + **spidev buffer** note (MIT)
- Diagnostic: [scripts/st7789_solid_fill_test.py](scripts/st7789_solid_fill_test.py) — solid colors only (isolates `image()` / full-frame path)
- Optional pip pin list: [requirements-display.txt](requirements-display.txt)
