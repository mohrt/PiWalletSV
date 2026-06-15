#!/usr/bin/env bash
# One-shot on a running Pi (as root): login on HDMI via tty2.
# Alpha images before this fix masked getty@tty1 but never enabled tty2.
set -euo pipefail
systemctl enable getty@tty2.service
systemctl start getty@tty2.service
echo "OK — plug HDMI, press Ctrl+Alt+F2 (Mac: Ctrl+Fn+Option+F2), login as pisv"
