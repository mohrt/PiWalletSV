"""Touch sign flow: camera scan, then verify, confirm, and a signed QR.

The camera worker matches the Zero. Once every frame is in, the screen
leaves the preview on its own and follows the same path as
``run_sign_flow``: decode, wallet fingerprint, SPV verify, confirm,
sign, then the signed-transaction QR. Cancel returns to the wallet menu.
"""

from __future__ import annotations

import threading
import time

from PIL import Image

from piwallet.bonnet.sign_scan import (
    _ScanState,
    _VerifyState,
    _apply_scan_progress,
    _make_default_verify_worker,
)
from piwallet.camera_lcd import paste_cover
from piwallet.core import derivation as deriv
from piwallet.core import envelope as env
from piwallet.core import sign as sgn
from piwallet.core.verify import VerifiedProposal, script_address_or_none
from piwallet.core.vault import VaultError
from piwallet.qr.camera_scan import ScanCancelled, scan_multipart_from_camera
from piwallet.qr.multipart import MultipartQrError, split_envelope_to_lines
from piwallet.touch.input import Tap
from piwallet.touch.manage import (
    _QR_BG,
    _address_size,
    _button,
    _cancel_hit,
    _draw_cancel,
    _icon_button,
)
from piwallet.touch.ui import Hit
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DANGER,
    COLOR_DIM,
    COLOR_FG,
    COLOR_OK,
    FrameBuffer,
)
from piwallet.ui.qr_brightness import (
    decrease_qr_background,
    increase_qr_background,
    qr_background_rgb,
)
from piwallet.ui.qr_render import render_qr
from piwallet.ui.widgets import draw_text

_MAX_FEE_RATE = 10_000
_QR_FRAME_S = 0.7
# A ~250-character PW1 line stays near QR version 10. On this panel that
# is about 4 px per module, the same density the xpub QR uses.
_SIGNED_CHUNK = 220


class SignScan:
    """Camera view, then the rest of signing."""

    def __init__(
        self,
        width: int,
        height: int,
        *,
        camera_rotation: int = 0,
        start_worker=None,
        vault=None,
        pin: str = "",
        wallet=None,
        qr_bg: int = _QR_BG,
    ) -> None:
        self.width = width
        self.height = height
        self.camera_rotation = camera_rotation
        self.vault = vault
        self.pin = pin
        self.wallet = wallet
        self.qr_bg = qr_bg
        self.state = _ScanState()
        self.phase = "scan"
        self.leave = False
        self.cancelled = False
        self._down: str | None = None
        self._seen: tuple | None = None
        self._handed = False
        self._message = ""
        self._progress = (0, 0)
        self._proposal: env.UnsignedProposal | None = None
        self._verified: VerifiedProposal | None = None
        self._verify: _VerifyState | None = None
        self._xpub = ""
        self._fp = b""
        self._frames: list[str] = []
        self._frame = 0
        self._frame_at = 0.0
        self._thread: threading.Thread | None = None
        if start_worker is None:
            from piwallet.bonnet.camera_preflight import preflight_camera_imports

            err = preflight_camera_imports()
            if err is not None:
                self.state.error = err.replace("\n", " ")[:80]
                self.state.finished = True
            else:
                start_worker = _camera_worker(camera_rotation)
        if start_worker is not None and not self.state.finished:
            start_worker(self.state)

    def on_tap(self, tap: Tap) -> None:
        hit = self._at(tap.x, tap.y)
        if tap.pressed:
            self._down = hit
            return
        chosen = self._down
        self._down = None
        if chosen is None or chosen != hit:
            return
        if chosen == "cancel":
            self._back()
            return
        if chosen == "accept" and self.phase == "confirm":
            self._start_signing()
            return
        if chosen == "brighter" and self.phase == "signed":
            self.qr_bg = increase_qr_background(self.qr_bg)
            self._frame = 0
            self._frame_at = time.monotonic()
            return
        if chosen == "dimmer" and self.phase == "signed":
            self.qr_bg = decrease_qr_background(self.qr_bg)
            self._frame = 0
            self._frame_at = time.monotonic()

    def poll(self) -> bool:
        """True when the screen should be painted again."""
        changed = self._pump()
        with self.state.lock:
            thumb = self.state.latest_thumb
            snap = (
                self.phase,
                self._message,
                self._frame,
                self._progress,
                id(thumb) if thumb is not None else 0,
                self.state.parts_received,
                self.state.parts_total,
                self.state.status_text,
                self.state.error,
                self.state.finished,
            )
        if snap != self._seen:
            self._seen = snap
            changed = True
        return changed

    def status(self) -> tuple[str, tuple[int, int, int]]:
        with self.state.lock:
            received = self.state.parts_received
            total = self.state.parts_total
            status_text = self.state.status_text
            error = self.state.error
            finished = self.state.finished
        if error:
            return error[:48], COLOR_DANGER
        if total > 0:
            if finished and received < total:
                received = total
            line = f"frame {received} / {total}"
            color = COLOR_OK if received >= total else COLOR_FG
            return line, color
        if status_text:
            return status_text[:48], COLOR_DIM
        return "Opening camera...", COLOR_DIM

    def summary(self) -> list[tuple[str, str]]:
        verified = self._verified
        if verified is None:
            return []
        send = sum(
            sats
            for index, (_script, sats) in enumerate(verified.outputs)
            if index != verified.change_index
        )
        network = "testnet" if self.wallet is not None and self.wallet.network == "test" else "mainnet"
        return [
            ("Send", f"{send:,} sat"),
            ("Fee", f"{verified.fee_sats:,} sat"),
            ("Net", network),
        ]

    def destinations(self) -> list[str]:
        """Payment addresses, leaving out the change output."""
        verified = self._verified
        if verified is None:
            return []
        network = self.wallet.network if self.wallet is not None else "main"
        found: list[str] = []
        for index, (script, _sats) in enumerate(verified.outputs):
            if index == verified.change_index:
                continue
            address = script_address_or_none(script, network=network)
            found.append(address if address else "Unrecognized script")
        return found

    def draw(self, fb: FrameBuffer) -> None:
        if self.phase == "scan":
            self._draw_scan(fb)
        elif self.phase == "confirm":
            self._draw_confirm(fb)
        elif self.phase == "signed":
            self._draw_signed(fb)
        elif self.phase == "verify":
            self._draw_verify(fb)
        else:
            self._draw_message(fb)

    def _pump(self) -> bool:
        if self.phase == "scan":
            return self._pump_scan()
        if self.phase == "verify":
            return self._pump_verify()
        if self.phase == "signed":
            return self._pump_signed()
        return False

    def _pump_scan(self) -> bool:
        if self._handed:
            return False
        with self.state.lock:
            finished = self.state.finished
            blob = self.state.assembled
        if not finished or blob is None:
            return False
        self._handed = True
        self.phase = "checking"
        self._message = "Checking proposal..."
        blob_copy = bytes(blob)

        def run() -> None:
            self._after_scan(blob_copy)

        self._thread = threading.Thread(target=run, name="piwallet-sign-check", daemon=True)
        self._thread.start()
        return True

    def _after_scan(self, blob: bytes) -> None:
        if self.leave:
            return
        try:
            decoded = env.decode(blob)
        except env.EnvelopeError as exc:
            self._fail(str(exc))
            return
        if not isinstance(decoded, env.UnsignedProposal):
            self._fail("Not a payment request")
            return
        if self.vault is None or self.wallet is None:
            self._fail("No wallet")
            return
        try:
            xpub = self.vault.get_account_xpub(self.pin, self.wallet.id)
        except VaultError as exc:
            self._fail(str(exc))
            return
        fp = deriv.key_fingerprint(deriv.parse_xpub(xpub))
        if fp != decoded.wallet_fp:
            self._fail("Wrong wallet")
            return
        if self.leave:
            return
        self._proposal = decoded
        self._xpub = xpub
        self._fp = fp
        verify = _VerifyState()
        verify.inputs_total = len(decoded.inputs)
        self._verify = verify
        _make_default_verify_worker(
            decoded,
            xpub,
            max_fee_rate_satskb=_MAX_FEE_RATE,
            network=self.wallet.network,
        )(verify)
        if self.leave:
            with verify.lock:
                verify.cancel_requested = True
            return
        self.phase = "verify"
        self._message = "Verifying..."

    def _pump_verify(self) -> bool:
        state = self._verify
        if state is None:
            return False
        with state.lock:
            finished = state.finished
            verified = state.verified
            error = state.error
            detail = state.detail_text
            done = state.inputs_done
            total = state.inputs_total
        if self.leave:
            return False
        message = (error or detail or "Verifying...")[:80]
        changed = message != self._message or (done, total) != self._progress
        self._message = message
        self._progress = (done, total)
        if finished and verified is not None:
            self._verified = verified
            self.phase = "confirm"
            self._message = ""
            return True
        if finished and error:
            self.phase = "error"
            self._message = error[:80]
            return True
        return changed

    def _start_signing(self) -> None:
        if self._verified is None or self.vault is None or self.wallet is None:
            self._fail("Nothing to sign")
            return
        self.phase = "signing"
        self._message = "Signing..."
        verified = self._verified
        fp = self._fp

        def run() -> None:
            if self.leave:
                return
            derive = lambda branch, index: self.vault.derive_signing_key(  # noqa: E731
                self.pin, self.wallet.id, branch, index
            )
            try:
                signed = sgn.build_signed_tx(verified, derive)
                envelope = sgn.to_signed_envelope(signed, wallet_fp=fp)
                lines = split_envelope_to_lines(
                    env.encode(envelope), max_encoded_chunk_chars=_SIGNED_CHUNK
                )
            except (sgn.SigningError, env.EnvelopeError, VaultError) as exc:
                self._fail(str(exc))
                return
            except Exception as exc:
                self._fail(str(exc))
                return
            if self.leave or not lines:
                if not lines and not self.leave:
                    self._fail("No QR data")
                return
            self._frames = lines
            self._frame = 0
            self._frame_at = time.monotonic()
            self.phase = "signed"
            self._message = ""

        self._thread = threading.Thread(target=run, name="piwallet-sign", daemon=True)
        self._thread.start()

    def _pump_signed(self) -> bool:
        if len(self._frames) < 2:
            return False
        now = time.monotonic()
        if now < self._frame_at + _QR_FRAME_S:
            return False
        self._frame = (self._frame + 1) % len(self._frames)
        self._frame_at = now
        return True

    def _fail(self, message: str) -> None:
        if self.leave:
            return
        self.phase = "error"
        self._message = message.replace("\n", " ")[:80]

    def _back(self) -> None:
        with self.state.lock:
            self.state.cancel_requested = True
        if self._verify is not None:
            with self._verify.lock:
                self._verify.cancel_requested = True
        self.cancelled = True
        self.leave = True

    def _at(self, x: int, y: int) -> str | None:
        for item in self._hits():
            if item.contains(x, y):
                return item.id
        return None

    def _hits(self) -> list[Hit]:
        hits = [_cancel_hit(self.width)]
        if self.phase == "confirm":
            hits.append(Hit("accept", 8, self.height - 48, self.width - 8, self.height - 6))
        elif self.phase == "signed":
            _x, _y, _side, brighter, dimmer = self._qr_layout()
            hits.extend((brighter, dimmer))
        return hits

    def _qr_layout(self) -> tuple[int, int, int, Hit, Hit]:
        btn = 44
        gap = 8
        btn_x1 = self.width - 8
        btn_x0 = btn_x1 - btn
        qr_left = 12
        qr_right = btn_x0 - gap
        side = max(80, qr_right - qr_left)
        qr_x = qr_left
        qr_y = 44
        pair = btn * 2 + gap
        top = qr_y + max(0, (side - pair) // 2)
        brighter = Hit("brighter", btn_x0, top, btn_x1, top + btn)
        dimmer = Hit("dimmer", btn_x0, top + btn + gap, btn_x1, top + pair)
        return qr_x, qr_y, side, brighter, dimmer

    def _draw_scan(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, "Scan to sign", size=18, color=COLOR_FG)
        _draw_cancel(fb, self.width, held=self._down == "cancel", label="Cancel")
        box = (8, 44, self.width - 8, self.height - 40)
        with self.state.lock:
            thumb = self.state.latest_thumb
        if thumb is not None:
            paste_cover(fb.image, thumb, box)
        else:
            fb.draw.rectangle(box, fill=(12, 12, 18))
            draw_text(
                fb,
                self.width // 2,
                (box[1] + box[3]) // 2,
                "Opening camera...",
                size=16,
                color=COLOR_DIM,
                anchor="mm",
            )
        line, color = self.status()
        draw_text(fb, self.width // 2, self.height - 22, line, size=16, color=color, anchor="mm")

    def _draw_verify(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, "Verifying", size=18, color=COLOR_FG)
        _draw_cancel(fb, self.width, held=self._down == "cancel", label="Cancel")
        done, total = self._progress
        shown = max(total, 1)
        frac = max(0.0, min(1.0, done / shown))
        y = 80
        fb.draw.rounded_rectangle((16, y, self.width - 16, y + 22), radius=6, fill=(40, 40, 48))
        fill = 16 + round((self.width - 32) * frac)
        if fill > 18:
            fb.draw.rounded_rectangle((16, y, fill, y + 22), radius=6, fill=COLOR_ACCENT)
        label = f"SPV {done}/{total}" if total else "SPV"
        draw_text(fb, self.width // 2, y + 36, label, size=16, color=COLOR_FG, anchor="mm")
        draw_text(fb, 16, y + 64, self._message[:48], size=14, color=COLOR_DIM)

    def _draw_confirm(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, "Sign transaction?", size=18, color=COLOR_FG)
        _draw_cancel(fb, self.width, held=self._down == "cancel", label="Cancel")
        verified = self._verified
        y = 56
        if verified is not None:
            count = len(verified.inputs)
            noun = "input" if count == 1 else "inputs"
            draw_text(fb, 16, y, f"SPV verified · {count} {noun}", size=16, color=COLOR_OK)
            y += 28
        for address in self.destinations():
            draw_text(fb, 16, y, "To", size=18, color=COLOR_DIM)
            y += 26
            size = _address_size(address, self.width - 16)
            draw_text(fb, self.width // 2, y, address, size=size, color=COLOR_FG, anchor="ma")
            y += size + 14
        for label, value in self.summary():
            draw_text(fb, 16, y, label, size=18, color=COLOR_DIM)
            draw_text(fb, self.width - 16, y, value, size=18, color=COLOR_FG, anchor="ra")
            y += 32
        for item in self._hits():
            if item.id == "accept":
                _button(fb, item, "Sign", held=self._down == "accept")

    def _draw_signed(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        count = len(self._frames)
        title = f"Signed {self._frame + 1}/{count}" if count else "Signed"
        draw_text(fb, 12, 8, title, size=18, color=COLOR_FG)
        _draw_cancel(fb, self.width, held=self._down == "cancel", label="Back")
        if not self._frames:
            return
        qr_x, qr_y, side, _bright, _dim = self._qr_layout()
        qr = render_qr(
            self._frames[self._frame],
            target_px=side,
            error="L",
            bg=qr_background_rgb(self.qr_bg),
        )
        fb.image.paste(qr, (qr_x, qr_y))
        for item in self._hits():
            if item.id in ("brighter", "dimmer"):
                _icon_button(fb, item, item.id, held=item.id == self._down)

    def _draw_message(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        title = "Signing..." if self.phase == "signing" else "Sign"
        if self.phase == "checking":
            title = "Sign"
        color = COLOR_DANGER if self.phase == "error" else COLOR_FG
        draw_text(fb, 12, 8, title, size=18, color=COLOR_FG)
        _draw_cancel(fb, self.width, held=self._down == "cancel", label="Cancel")
        y = 64
        for line in _wrap(self._message, 26)[:6]:
            draw_text(fb, 16, y, line, size=16, color=color)
            y += 24


def _wrap(text: str, limit: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if len(candidate) > limit and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def _camera_worker(rotation: int):
    def start_worker(state: _ScanState) -> None:
        def run() -> None:
            def on_progress(have: int, msg: str) -> None:
                _apply_scan_progress(state, have, msg)

            def on_thumb(img: Image.Image) -> None:
                with state.lock:
                    state.latest_thumb = img

            def cancel_check() -> bool:
                with state.lock:
                    return state.cancel_requested

            try:
                blob = scan_multipart_from_camera(
                    rotation_degrees=rotation,
                    on_progress=on_progress,
                    on_lcd_thumbnail=on_thumb,
                    cancel_check=cancel_check,
                )
            except ScanCancelled:
                with state.lock:
                    state.finished = True
                return
            except (MultipartQrError, RuntimeError) as exc:
                with state.lock:
                    state.error = str(exc)[:80]
                    state.finished = True
                return
            except Exception as exc:
                with state.lock:
                    state.error = f"camera error: {exc}"[:80]
                    state.finished = True
                return
            with state.lock:
                state.assembled = blob
                state.finished = True
                if state.parts_total > 0:
                    state.parts_received = state.parts_total

        threading.Thread(target=run, name="piwallet-scan", daemon=True).start()

    return start_worker
