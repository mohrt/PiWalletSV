# Pi Zero WH + 1.3" TFT bonnet — quick setup

**Bonnet test (now):** do **§§1–2**, skim **§3**, then **§§4–7**. **§7** needs **one file** copied from your Mac (`scp` the demo script); you do **not** need the whole repo on the Pi.

**Wallet / air-gapped signer (later):** when you are ready to run your own code on the Pi, copy or sync the `PiWallet` project (or whatever you ship) onto the device. That is optional and not part of the display smoke test.

---

## 1. Hardware

- Fit the **bonnet** straight onto the **40-pin** header (Pi off).
- Power from **PWR IN**: the micro-USB **farthest from the SD slot**. The one **closer to the SD slot** is USB **data** only.

## 2. Flash OS (Imager)

- **Raspberry Pi OS Lite (32-bit), Bookworm**
- Turn on **SSH**, set **user** / **password** / **hostname** / **Wi‑Fi** as you like. Leave **Raspberry Pi Connect** off.
- Boot and **SSH** in (`ssh user@hostname.local` may take a minute the first time).

## 3. Skip this while testing the bonnet

**Do not copy `PiWallet` from your Mac** for the bring-up in this guide. Having the repo on the Mac (Cursor, git, etc.) is fine; the Pi only needs **§§4–7** to exercise the display.

When you later want **your** wallet code on the air-gapped Pi, copy the project then — for example from the Mac, in the parent directory of your repo:

```bash
scp -r PiWallet YOUR_USER@YOUR_PI.local:~/
```

Then on the Pi you can `cd ~/PiWallet` and run your own scripts instead of only the demo in `~/piwallet-demo/`.

## 4. SPI + packages (on the Pi)

```bash
sudo raspi-config nonint do_spi 0
sudo reboot
```

After it comes back:

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv python3-pil python3-numpy fonts-dejavu
```

**Raspberry Pi OS / `spidev` (important on Pi Zero):** the demo sends ~**115 KiB** per frame. The default **`spidev` transfer buffer** is often **4 KiB**, which shows up as a **clean band on one side and garbage on the rest**. On **Bookworm**, `spidev` is usually **built into the kernel**, so **`/etc/modprobe.d/...` is often ignored**. Set the buffer on the **kernel command line** instead (must stay **one line** in the file):

1. Edit cmdline (Bookworm path):

   ```bash
   sudo nano /boot/firmware/cmdline.txt
   ```

2. At the **end of the existing single line**, add a space and:

   `spidev.bufsiz=131072`

3. Save, then reboot:

   ```bash
   sudo reboot
   ```

4. Check:

   ```bash
   cat /sys/module/spidev/parameters/bufsiz
   ```

   You want **131072**. If it is still **4096**, the cmdline edit did not apply (typo, extra newline, or wrong file — older images used `/boot/cmdline.txt`).

**Optional (only if `spidev` is a loadable module on your image):**  
`echo 'options spidev bufsiz=131072' | sudo tee /etc/modprobe.d/spidev.conf` then reboot — use **either** cmdline **or** modprobe, not a substitute for cmdline on typical Bookworm.

## 5. Venv, Blinka, display libs

```bash
mkdir -p ~/.venvs
python3 -m venv ~/.venvs/piwallet --system-site-packages
source ~/.venvs/piwallet/bin/activate
pip install --upgrade pip setuptools wheel
pip install adafruit-python-shell
wget -q https://raw.githubusercontent.com/adafruit/Raspberry-Pi-Installer-Scripts/main/raspi-blinka.py
sudo -E env PATH=$PATH python3 raspi-blinka.py
```

Reboot when the script asks. SSH back in, then:

```bash
source ~/.venvs/piwallet/bin/activate
pip install adafruit-blinka adafruit-circuitpython-rgb-display Pillow
```

(After any reboot, run `source ~/.venvs/piwallet/bin/activate` before Python.)

## 6. Free SPI chip-select for the bonnet driver

```bash
source ~/.venvs/piwallet/bin/activate
pip install --upgrade adafruit-python-shell click
wget -q https://raw.githubusercontent.com/adafruit/Raspberry-Pi-Installer-Scripts/main/raspi-spi-reassign.py
sudo -E env PATH=$PATH python3 raspi-spi-reassign.py --ce0 disabled --ce1 disabled
sudo reboot
```

If you get a **menu** instead: choose **Reassign**, set **CE0** and **CE1** to **Disabled** (do **not** pick “Disable SPI”).

## 7. Run the bonnet demo

**Use the script from this repo on your Mac** ([scripts/rgb_display_pillow_bonnet_buttons.py](scripts/rgb_display_pillow_bonnet_buttons.py)), not a blind `wget` of Adafruit’s upstream file: upstream matches Adafruit’s docs but omits **Pi Zero–friendly** tweaks (NumPy blit off, lower SPI `BAUDRATE`) this project added.

On your **Mac** (parent folder of `PiWallet`):

```bash
ssh YOUR_USER@YOUR_PI.local mkdir -p ~/piwallet-demo
scp PiWallet/scripts/rgb_display_pillow_bonnet_buttons.py YOUR_USER@YOUR_PI.local:~/piwallet-demo/
```

On the **Pi**:

```bash
cd ~/piwallet-demo
source ~/.venvs/piwallet/bin/activate
python3 rgb_display_pillow_bonnet_buttons.py
```

You should see color graphics and **Hello World**; joystick and **A** / **B** change the picture. **Ctrl+C** to stop.

### 7b. If the demo is still garbled (e.g. Pi Zero **W v1.1** + `bufsiz` already 131072)

Run a **minimal test** that never calls `disp.image()` — only full-screen solid colors (different SPI pattern than the PIL demo):

On the Mac:

```bash
scp PiWallet/scripts/st7789_solid_fill_test.py YOUR_USER@YOUR_PI.local:~/piwallet-demo/
```

On the Pi:

```bash
cd ~/piwallet-demo
source ~/.venvs/piwallet/bin/activate
python3 st7789_solid_fill_test.py
```

- **Whole panel** flashes **red / green / blue** evenly → wiring and ST7789 init are mostly OK; focus on **full-frame `image()` / RAMWR** (Pi Zero + Blinka + `adafruit_rgb_display`), or try a **Pi Zero 2 W** for the same Python stack.
- **Still a “good half + garbage”** (or wrong colors in bands) → treat as **hardware**: re-seat the bonnet, confirm **Adafruit SKU [4506](https://www.adafruit.com/product/4506)** (not a different 1.3" / ST7789 board), then try Adafruit **stack B** ([kernel installer](https://learn.adafruit.com/adafruit-1-3-color-tft-bonnet-for-raspberry-pi/kernel-module-install) with `--display=st7789v_bonnet_240x240`) to see if the **kernel** framebuffer is clean (uninstall stack B before going back to Python SPI).

**Garbled / “good on one side, noise on the other”:** apply **`spidev.bufsiz=131072`** on **`/boot/firmware/cmdline.txt`** (§4). Confirm `cat /sys/module/spidev/parameters/bufsiz` → **131072**. Then run **§7** and **§7b** as above. **`modprobe.d` alone often does nothing** when `spidev` is built-in.

---

## Adafruit’s own documentation (what “correct” is)

Official guide: **[Adafruit 1.3" Color TFT Bonnet for Raspberry Pi](https://learn.adafruit.com/adafruit-1-3-color-tft-bonnet-for-raspberry-pi)** — product **[4506](https://www.adafruit.com/product/4506)** (240×240 IPS, SPI, ST7789-class panel; kernel tooling refers to **`st7789v`**).

**Hardware:** [Pinouts](https://learn.adafruit.com/adafruit-1-3-color-tft-bonnet-for-raspberry-pi/pinouts) — SPI **SCK / MOSI / CE0**, **GPIO25** = DC, **GPIO26** = backlight; joystick **GPIO17 / 22 / 27 / 23**, center **GPIO4**; buttons **GPIO5** & **GPIO6** (with 10k pull-ups). The Adafruit demo uses **GPIO24** reset, same as their [upstream example](https://github.com/adafruit/Adafruit_CircuitPython_RGB_Display/blob/main/examples/rgb_display_pillow_bonnet_buttons.py).

**Two stacks Adafruit documents (use one for the TFT, not both at once):**

- **A — Python / Blinka / PIL** — [Python setup](https://learn.adafruit.com/adafruit-1-3-color-tft-bonnet-for-raspberry-pi/python-setup) + [CircuitPython on Raspberry Pi](https://learn.adafruit.com/circuitpython-on-raspberrypi-linux). User-space **`adafruit-circuitpython-rgb-display`** + **`adafruit-blinka`**. Needs **SPI on**, **`raspi-blinka.py`**, then **`raspi-spi-reassign.py --ce0 disabled --ce1 disabled`** (Adafruit’s Python page still shows only `--ce0=disabled`; current **`raspi-spi-reassign.py` requires both `--ce0` and `--ce1`**). Demo: **`ST7789(..., height=240, y_offset=80, rotation=180, ...)`** — same geometry as Adafruit’s **`adafruit-pitft.py`** profile **`st7789v_bonnet_240x240`** at **180°** (`y-offset=80` in their installer config).

- **B — Kernel DRM / framebuffer** — [Kernel module install](https://learn.adafruit.com/adafruit-1-3-color-tft-bonnet-for-raspberry-pi/kernel-module-install). Clone **[Raspberry-Pi-Installer-Scripts](https://github.com/adafruit/Raspberry-Pi-Installer-Scripts)** and run:  
  `sudo -E env PATH=$PATH python3 adafruit-pitft.py --display=st7789v_bonnet_240x240 --rotation=0 --install-type=console`  
  That installs **`drm-tftbonnet13`** / **`fb_st7789v`** for a **text console** on the TFT. Good to prove the panel with the kernel driver; **uninstall** (`--install-type=uninstall`) before expecting stack **A** to own SPI/CE0 again.

This guide follows **stack A** (PIL + buttons + joystick on Lite). **Stack B** is Adafruit’s path for **framebuffer console**, not mixed with stack **A** without uninstalling B.

---

## Done

**Bonnet:** working.

**Camera (CSI):** confirm with `rpicam-hello` once the cable seats correctly. After `pip install pyzbar` + `sudo apt install libzbar0t64`, multipart animated codes from the phone can be assembled on-device with::

    piwallet qr scan-camera -o /tmp/proposal.bin

Pipe the same ``PW1|…`` lines on a laptop with ``piwallet qr join -o proposal.bin``. Then verify/sign with ``piwallet decode …`` / ``piwallet sign …``.

**PiWalletSV repo:** install with ``pip install -e ".[dev]"`` on Python 3.13 (see README).

**More detail if something breaks:** [Adafruit 1.3" bonnet Python setup](https://learn.adafruit.com/adafruit-1-3-color-tft-bonnet-for-raspberry-pi/python-setup) · [CircuitPython on Raspberry Pi](https://learn.adafruit.com/circuitpython-on-raspberrypi-linux)
