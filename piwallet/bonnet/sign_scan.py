"""Bonnet sign-from-camera flow.

Four-screen sequence wired up by :func:`run_sign_flow`:

1. :class:`ScanProposalScreen` — runs :func:`scan_multipart_from_camera`
   in a worker thread (pyzbar decode at 1280x960 is too slow for the
   30 fps UI thread), surfaces a live LCD preview + a status line that
   tracks ``frames N / M`` as fragments arrive.
2. :class:`VerifyProposalScreen` — runs :func:`verify_proposal` in a
   worker thread with per-input SPV progress; auto-advances on success.
3. :class:`ConfirmProposalScreen` — shows a verified summary with an
   **SPV verified** badge; **A** confirms, **B** cancels.
4. :class:`PairingMultipartQrScreen` — reused from the companion
   pairing flow to animate the resulting ``signed_tx`` envelope back
   to the companion as ``PW1|`` frames.

Threading model
---------------
The worker thread owns the camera and assembler. The UI thread reads
:class:`_ScanState` (mutex-protected) every frame to paint the latest
thumbnail and status line, and flips ``cancel_requested`` to ``True``
when the operator presses **A** or **B**. The worker polls that flag between
camera frames and raises :class:`ScanCancelled` to break out cleanly.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image

from piwallet.bonnet.companion_pairing import pairing_pw1_lines  # noqa: F401  # re-exported for tests
from piwallet.camera_lcd import paste_cover
from piwallet.core import derivation as deriv
from piwallet.core.settings import BonnetSettings
from piwallet.core import envelope as env
from piwallet.core import sign as sgn
from piwallet.core import verify as vfy
from piwallet.core.vault import Vault, VaultError, VaultWipedError, WalletRecord
from piwallet.qr.camera_scan import ScanCancelled, scan_multipart_from_camera
from piwallet.qr.multipart import MultipartQrError, split_envelope_to_lines
from piwallet.ui.app import IdleWakeTracker, run_screen
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DANGER,
    COLOR_DIM,
    COLOR_FG,
    COLOR_OK,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    Display,
    FrameBuffer,
)
from piwallet.ui.input import Button, Event, EventKind, InputManager
from piwallet.bonnet.qr_settings import qr_brightness_screen_kwargs
from piwallet.ui.pairing_multipart_qr_screen import PairingMultipartQrScreen
from piwallet.ui.widgets import Modal, ProgressBar, draw_text

log = logging.getLogger(__name__)

#: Outcomes from :func:`run_sign_flow` — mirrors :data:`WalletManageResult`.
SignFlowResult = Literal["stay"]


# ---------------------------------------------------------------------------
# Worker-thread shared state
# ---------------------------------------------------------------------------


@dataclass
class _ScanState:
    """Thread-safe snapshot the UI thread reads every frame.

    All mutations go through :attr:`lock`; readers copy the fields
    they need under the same lock and release it before painting.
    """

    lock: threading.Lock = field(default_factory=threading.Lock)
    latest_thumb: Image.Image | None = None
    parts_received: int = 0
    parts_total: int = 0
    status_text: str = "Aiming..."
    error: str | None = None
    assembled: bytes | None = None
    finished: bool = False
    cancel_requested: bool = False


def _apply_scan_progress(state: _ScanState, have: int, msg: str) -> None:
    """Update scan counters from a camera-scan progress callback.

    Ignores ambiguous post-complete updates (``have == 0`` with a bare
    ``"fragment"`` message) so the UI does not regress from ``9/10`` to
    ``0/10`` when the assembler resets after the last frame.
    """
    with state.lock:
        if "/" in msg and "fragment" in msg:
            try:
                tail = msg.split("fragment ", 1)[1]
                num, den = tail.split("/", 1)
                state.parts_received = int(num)
                state.parts_total = int(den)
            except (ValueError, IndexError):
                if have > 0:
                    state.parts_received = have
                state.status_text = msg
        elif have > 0:
            state.parts_received = have
            state.status_text = msg
        else:
            # Bare "fragment" or "frame N: no QR" — keep the last count.
            state.status_text = msg


# ---------------------------------------------------------------------------
# Scan screen
# ---------------------------------------------------------------------------


# Layout for the 240 x 240 panel. We give the preview a generous square
# region so the operator can frame the companion's QR from arm's length;
# the status line + footer hint stack at the bottom.
_TITLE_H: int = 22
_PREVIEW_TOP: int = _TITLE_H + 2
_PREVIEW_BOTTOM: int = DISPLAY_HEIGHT - 38
_STATUS_Y: int = DISPLAY_HEIGHT - 24
_FOOTER_Y: int = DISPLAY_HEIGHT - 10


@dataclass
class ScanProposalScreen:
    """Live-preview QR scanner with worker-thread pyzbar decode.

    The screen does **not** own the worker — it accepts an injected
    ``start_worker`` callable so tests can drive the screen without
    spawning threads or touching ``picamera2``. The bonnet entry
    point :func:`run_sign_flow` wires up the production worker.
    """

    title: str = "Scan to sign"
    state: _ScanState = field(default_factory=_ScanState)
    done: bool = False
    result: bytes | str | None = None  # bytes when assembled; "cancel" otherwise
    _started: bool = field(init=False, default=False)
    # Test seam: the bonnet wires this to a thread that calls
    # :func:`scan_multipart_from_camera`. Tests inject a no-op or
    # synchronous fake.
    start_worker: callable = field(default=None)  # type: ignore[assignment]

    def _ensure_started(self) -> None:
        if self._started or self.start_worker is None:
            return
        self._started = True
        try:
            self.start_worker(self.state)
        except Exception as exc:
            log.exception("scan worker start failed")
            with self.state.lock:
                self.state.error = str(exc)
                self.state.finished = True

    # -- input handling ----------------------------------------------

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if (b == Button.B and k == EventKind.PRESS) or (
            b == Button.A and k == EventKind.PRESS
        ):
            with self.state.lock:
                self.state.cancel_requested = True
            self.done = True
            self.result = "cancel"
            return

    # -- rendering ---------------------------------------------------

    def draw(self, fb: FrameBuffer) -> None:
        self._ensure_started()

        with self.state.lock:
            thumb = self.state.latest_thumb
            received = self.state.parts_received
            total = self.state.parts_total
            status_text = self.state.status_text
            error = self.state.error
            blob = self.state.assembled
            finished = self.state.finished

        # Worker finished — promote its result to the screen so
        # ``run_screen`` exits and the orchestrator can move on.
        if finished and not self.done:
            if blob is not None:
                self.done = True
                self.result = blob
                if total > 0:
                    received = total
            elif error is not None:
                self.done = True
                self.result = "cancel"
                return

        fb.clear(COLOR_BG)
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, _TITLE_H), fill=(20, 20, 32))
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            _TITLE_H // 2,
            self.title,
            size=12,
            color=COLOR_ACCENT,
            anchor="mm",
        )

        box = (0, _PREVIEW_TOP, DISPLAY_WIDTH, _PREVIEW_BOTTOM)
        if thumb is not None:
            paste_cover(fb.image, thumb, box)
        else:
            # Dim placeholder while the camera is settling; avoids
            # the eye-catching black-on-black-on-startup look.
            fb.draw.rectangle(box, fill=(12, 12, 18))
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                (_PREVIEW_TOP + _PREVIEW_BOTTOM) // 2,
                "Opening camera...",
                size=11,
                color=COLOR_DIM,
                anchor="mm",
            )

        # Status line: prefer the structured "frames N / M" derived
        # from assembler state; fall back to whatever the worker put
        # in ``status_text`` (during the no-QR-yet phase).
        if total > 0:
            line = f"frame {received} / {total}"
            color = COLOR_OK if received >= total else COLOR_FG
        else:
            line = status_text
            color = COLOR_DIM
        if error is not None:
            line = error[:40]
            color = COLOR_DANGER
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            _STATUS_Y,
            line,
            size=11,
            color=color,
            anchor="mm",
        )

        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            _FOOTER_Y,
            "A/B back",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )


# ---------------------------------------------------------------------------
# Verify screen
# ---------------------------------------------------------------------------


@dataclass
class _VerifyState:
    """Thread-safe snapshot the verify worker and UI thread share."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    detail_text: str = "Starting…"
    inputs_done: int = 0
    inputs_total: int = 0
    verified: vfy.VerifiedProposal | None = None
    error: str | None = None
    finished: bool = False
    cancel_requested: bool = False


def _parse_spv_progress(msg: str) -> tuple[int | None, int | None]:
    """Extract ``(n, m)`` from messages like ``SPV 1/2: Merkle…``."""
    if not msg.startswith("SPV ") or "/" not in msg:
        return None, None
    try:
        rest = msg[4:]
        num_str, rest2 = rest.split("/", 1)
        den_str = rest2.split(":", 1)[0]
        return int(num_str), int(den_str)
    except (ValueError, IndexError):
        return None, None


_VERIFY_BAR_Y: int = _PREVIEW_TOP + 50
_VERIFY_DETAIL_Y: int = _STATUS_Y


@dataclass
class VerifyProposalScreen:
    """SPV verification with live progress; auto-advances on success."""

    proposal: env.UnsignedProposal
    account_xpub_str: str
    network: str = "main"
    max_fee_rate_satskb: int | None = 10_000
    title: str = "Verifying SPV"
    state: _VerifyState = field(default_factory=_VerifyState)
    done: bool = False
    result: vfy.VerifiedProposal | None = None
    _started: bool = field(init=False, default=False)
    start_worker: callable = field(default=None)  # type: ignore[assignment]

    def _ensure_started(self) -> None:
        if self._started or self.start_worker is None:
            return
        self._started = True
        with self.state.lock:
            self.state.inputs_total = len(self.proposal.inputs)
        try:
            self.start_worker(self.state)
        except Exception as exc:
            log.exception("verify worker start failed")
            with self.state.lock:
                self.state.error = str(exc)
                self.state.finished = True

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if (b == Button.B and k == EventKind.PRESS) or (
            b == Button.A and k == EventKind.PRESS
        ):
            with self.state.lock:
                self.state.cancel_requested = True
            self.done = True
            return

    def draw(self, fb: FrameBuffer) -> None:
        self._ensure_started()

        with self.state.lock:
            detail = self.state.detail_text
            inputs_done = self.state.inputs_done
            inputs_total = self.state.inputs_total
            verified = self.state.verified
            error = self.state.error
            finished = self.state.finished

        if finished and not self.done:
            if verified is not None:
                self.done = True
                self.result = verified
                return
            if error is not None:
                # Stay on screen until the operator presses B.
                pass

        fb.clear(COLOR_BG)
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, _TITLE_H), fill=(20, 20, 32))
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            _TITLE_H // 2,
            self.title,
            size=12,
            color=COLOR_ACCENT,
            anchor="mm",
        )

        total = max(1, inputs_total)
        bar = ProgressBar(
            label=f"SPV {inputs_done}/{inputs_total}" if inputs_total else "SPV",
            value=float(inputs_done),
            total=float(total),
            y=_VERIFY_BAR_Y,
        )
        pad = 24
        bar_h = 20
        fb.draw.rectangle(
            (pad, bar.y, DISPLAY_WIDTH - pad, bar.y + bar_h),
            fill=(40, 40, 48),
            outline=COLOR_DIM,
        )
        if bar.total > 0:
            frac = max(0.0, min(1.0, bar.value / bar.total))
            fill_width = round((DISPLAY_WIDTH - 2 * pad) * frac)
            if fill_width > 0:
                fb.draw.rectangle(
                    (pad, bar.y, pad + fill_width, bar.y + bar_h),
                    fill=bar.color,
                )
        if bar.label:
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                bar.y - 12,
                bar.label,
                size=12,
                color=COLOR_FG,
                anchor="mm",
            )

        line = error[:40] if error else detail[:40]
        color = COLOR_DANGER if error else COLOR_DIM
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            _VERIFY_DETAIL_Y,
            line,
            size=11,
            color=color,
            anchor="mm",
        )

        footer = "B cancel" if error else "A/B back"
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            _FOOTER_Y,
            footer,
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )


def _make_default_verify_worker(
    proposal: env.UnsignedProposal,
    account_xpub_str: str,
    *,
    max_fee_rate_satskb: int | None,
    network: str,
):
    """Factory returning a ``start_worker(state)`` for SPV verification."""

    def start_worker(state: _VerifyState) -> None:
        def run() -> None:
            def on_progress(msg: str) -> None:
                with state.lock:
                    state.detail_text = msg
                    n, m = _parse_spv_progress(msg)
                    if m is not None:
                        state.inputs_total = m
                    if n is not None and "OK @" in msg:
                        state.inputs_done = n

            def cancel_check() -> bool:
                with state.lock:
                    return state.cancel_requested

            if cancel_check():
                with state.lock:
                    state.finished = True
                return
            try:
                verified = vfy.verify_proposal(
                    proposal,
                    account_xpub_str,
                    max_fee_rate_satskb=max_fee_rate_satskb,
                    network=network,  # type: ignore[arg-type]
                    on_progress=on_progress,
                )
            except vfy.ProposalVerificationError as exc:
                with state.lock:
                    state.error = str(exc)
                    state.finished = True
                return
            except Exception as exc:  # pragma: no cover
                log.exception("verify worker crashed")
                with state.lock:
                    state.error = str(exc)
                    state.finished = True
                return
            with state.lock:
                state.verified = verified
                state.inputs_done = state.inputs_total
                state.finished = True

        thread = threading.Thread(target=run, name="piwallet-verify", daemon=True)
        thread.start()

    return start_worker


# ---------------------------------------------------------------------------
# Confirm screen
# ---------------------------------------------------------------------------


# Returned via ``ConfirmProposalScreen.result``.
ConfirmResult = Literal["sign", "cancel"]


@dataclass
class ConfirmProposalScreen:
    """Show a verified proposal summary; **A** confirms, **B** cancels.

    When ``verified`` is injected (from :class:`VerifyProposalScreen`),
    :func:`verify_proposal` is not run again. Otherwise verification
    runs in :meth:`__post_init__` for backward compatibility.
    """

    proposal: env.UnsignedProposal
    account_xpub_str: str
    network: str = "main"
    max_fee_rate_satskb: int | None = 10_000
    title: str = "Sign transaction?"
    verified: vfy.VerifiedProposal | None = None
    done: bool = False
    result: ConfirmResult | None = None
    verify_error: str | None = None

    def __post_init__(self) -> None:
        if self.verified is not None:
            return
        try:
            self.verified = vfy.verify_proposal(
                self.proposal,
                self.account_xpub_str,
                max_fee_rate_satskb=self.max_fee_rate_satskb,
                network=self.network,  # type: ignore[arg-type]
            )
        except vfy.ProposalVerificationError as exc:
            self.verify_error = str(exc)

    # -- input handling ----------------------------------------------

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if b == Button.B and k == EventKind.PRESS:
            self.done = True
            self.result = "cancel"
            return
        if (
            b == Button.A
            and k == EventKind.PRESS
            and self.verified is not None
            and self.verify_error is None
        ):
            self.done = True
            self.result = "sign"

    # -- rendering ---------------------------------------------------

    def _send_sats(self, v: vfy.VerifiedProposal) -> int:
        """Sum of all non-change outputs — the amount actually leaving the wallet."""
        return sum(
            sats
            for idx, (_script, sats) in enumerate(v.outputs)
            if idx != v.change_index
        )

    def draw(self, fb: FrameBuffer) -> None:
        from piwallet.ui.widgets import wrap_text_lines

        fb.clear(COLOR_BG)
        title_h = 22
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, title_h), fill=(20, 20, 32))
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            title_h // 2,
            self.title,
            size=13,
            color=COLOR_ACCENT,
            anchor="mm",
        )

        if self.verify_error is not None:
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                title_h + 14,
                "Proposal rejected",
                size=12,
                color=COLOR_DANGER,
                anchor="mm",
            )
            lines = wrap_text_lines(self.verify_error, max_chars=30)[:6]
            y = title_h + 36
            for ln in lines:
                draw_text(
                    fb, DISPLAY_WIDTH // 2, y, ln, size=10, color=COLOR_FG, anchor="mm"
                )
                y += 14
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                _FOOTER_Y,
                "B cancel",
                size=10,
                color=COLOR_DIM,
                anchor="mm",
            )
            return

        assert self.verified is not None
        v = self.verified
        n_inputs = len(v.inputs)
        inp_label = "input" if n_inputs == 1 else "inputs"

        y = title_h + 14
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            y,
            f"SPV verified · {n_inputs} {inp_label}",
            size=11,
            color=COLOR_OK,
            anchor="mm",
        )
        y += 14
        if v.input_heights:
            lo, hi = min(v.input_heights), max(v.input_heights)
            blocks = f"block {lo}" if lo == hi else f"blocks {lo}–{hi}"
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                y,
                blocks,
                size=10,
                color=COLOR_OK,
                anchor="mm",
            )
            y += 16

        rows = [
            ("Send", f"{self._send_sats(v):,} sat"),
            ("Fee", f"{v.fee_sats:,} sat"),
            ("Net", self.network),
        ]

        row_gap = 20
        for label, value in rows:
            draw_text(fb, 12, y, label, size=12, color=COLOR_DIM, anchor="lm")
            draw_text(fb, DISPLAY_WIDTH - 12, y, value, size=12, color=COLOR_FG, anchor="rm")
            y += row_gap

        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            _FOOTER_Y,
            "A confirm, B cancel",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )


# ---------------------------------------------------------------------------
# Worker thread factory
# ---------------------------------------------------------------------------


def _preflight_camera_imports() -> str | None:
    """Force-import picamera2 + libcamera on the **main** thread.

    Returns ``None`` on success or a short human-readable error
    string on failure.

    Why this exists: on Raspberry Pi OS the libcamera Python binding
    initialises a C-side logger and ipa proxy on first import, and
    a few users have reported that step failing when the *first*
    import happens inside a freshly-spawned worker thread (entropy
    capture works fine because that flow imports from the main UI
    thread). Pre-warming ``sys.modules`` here means the worker's
    later ``from libcamera import controls`` lands a cached module
    object, never re-triggering the C init.

    Doubles as an early-failure surface for venvs missing
    ``--system-site-packages`` or the ``python3-picamera2`` apt
    package — the operator sees a single targeted modal instead of
    a worker-thread crash mid-scan.
    """
    try:
        import libcamera  # type: ignore[import-not-found]  # noqa: F401
        import picamera2  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return (
            "Camera stack missing.\n"
            "sudo apt install python3-picamera2\n"
            "venv needs --system-site-packages"
        )
    return None


def _make_default_worker(
    *,
    capture_size: str = "640x480",
    interval_s: float = 0.35,
    settle_s: float = 1.0,
    skip_autofocus: bool = False,
):
    """Factory returning a ``start_worker(state)`` callable.

    Production callers leave the defaults; tests pass a stub.
    """

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
                    size=capture_size,
                    interval_s=interval_s,
                    settle_s=settle_s,
                    skip_autofocus=skip_autofocus,
                    on_progress=on_progress,
                    on_lcd_thumbnail=on_thumb,
                    cancel_check=cancel_check,
                )
            except ScanCancelled:
                with state.lock:
                    state.finished = True
                return
            except (MultipartQrError, RuntimeError) as exc:
                log.warning("scan worker failed: %s", exc)
                with state.lock:
                    state.error = str(exc)
                    state.finished = True
                return
            except Exception as exc:  # pragma: no cover (defensive)
                log.exception("scan worker crashed")
                with state.lock:
                    state.error = f"camera error: {exc}"
                    state.finished = True
                return
            with state.lock:
                state.assembled = blob
                state.finished = True
                if state.parts_total > 0:
                    state.parts_received = state.parts_total

        thread = threading.Thread(target=run, name="piwallet-scan", daemon=True)
        thread.start()

    return start_worker


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _show_modal(
    display: Display,
    *,
    title: str,
    body: str,
    accent: tuple[int, int, int],
    hold_seconds: float,
) -> None:
    fb = FrameBuffer(display.width, display.height)
    Modal(title=title, body=body, footer="", accent=accent).draw(fb)
    display.flip(fb)
    if hold_seconds > 0:
        time.sleep(hold_seconds)


def run_sign_flow(
    display: Display,
    input_mgr: InputManager,
    vault: Vault,
    pin: str,
    wallet: WalletRecord,
    *,
    target_fps: int = 30,
    toast_seconds: float = 2.0,
    idle_wake: IdleWakeTracker | None = None,
    start_worker=None,  # test seam (scan)
    start_verify_worker=None,  # test seam (SPV verify)
    max_fee_rate_satskb: int = 10_000,
    settings: BonnetSettings | None = None,
    settings_path: Path | None = None,
    on_settings_changed: Callable[[BonnetSettings], None] | None = None,
) -> SignFlowResult:
    """Drive scan → confirm → sign → animate signed_tx.

    Returns ``"stay"`` for every terminal state (cancel, error toast,
    or successful sign). The caller (``run_wallet_manage``) redraws
    the manage menu.
    """

    # ---- 1. Scan the unsigned_proposal ---------------------------------
    if start_worker is None:
        # Pre-import the camera stack on the main thread (prevents the
        # libcamera-on-worker-thread init quirk and surfaces a missing
        # `python3-picamera2` apt package as a clean modal up front).
        cam_err = _preflight_camera_imports()
        if cam_err is not None:
            _show_modal(
                display,
                title="Camera unavailable",
                body=cam_err,
                accent=COLOR_DANGER,
                hold_seconds=toast_seconds,
            )
            return "stay"
        skip_af = settings is not None and settings.camera_type not in ("imx708", "auto")
        start_worker = _make_default_worker(skip_autofocus=skip_af)
    scan = ScanProposalScreen(start_worker=start_worker)
    run_screen(display, input_mgr, scan, target_fps=target_fps, idle_wake=idle_wake)

    if not isinstance(scan.result, (bytes, bytearray)):
        # B-press, error, or anything other than a complete blob.
        # If the worker reported an error, surface it briefly.
        with scan.state.lock:
            err = scan.state.error
        if err is not None:
            _show_modal(
                display,
                title="Scan failed",
                body=err[:96],
                accent=COLOR_DANGER,
                hold_seconds=toast_seconds,
            )
        return "stay"
    blob = bytes(scan.result)

    # ---- 2. Decode + sanity-check envelope type ------------------------
    try:
        decoded = env.decode(blob)
    except env.EnvelopeError as exc:
        _show_modal(
            display,
            title="Decode failed",
            body=str(exc)[:96],
            accent=COLOR_DANGER,
            hold_seconds=toast_seconds,
        )
        return "stay"
    if not isinstance(decoded, env.UnsignedProposal):
        _show_modal(
            display,
            title="Wrong envelope",
            body=f"got {type(decoded).__name__}, expected unsigned_proposal",
            accent=COLOR_DANGER,
            hold_seconds=toast_seconds,
        )
        return "stay"

    # ---- 3. Wallet binding check (xpub fingerprint) --------------------
    try:
        xpub_str = vault.get_account_xpub(pin, wallet.id)
    except (VaultError, VaultWipedError) as exc:
        _show_modal(
            display,
            title="Vault error",
            body=str(exc)[:96],
            accent=COLOR_DANGER,
            hold_seconds=toast_seconds,
        )
        return "stay"
    fp = deriv.key_fingerprint(deriv.parse_xpub(xpub_str))
    if fp != decoded.wallet_fp:
        _show_modal(
            display,
            title="Wrong wallet",
            body=(
                f"proposal fp={decoded.wallet_fp.hex()[:8]}\n"
                f"this wallet fp={fp.hex()[:8]}"
            ),
            accent=COLOR_DANGER,
            hold_seconds=toast_seconds,
        )
        return "stay"

    # ---- 4. SPV verify (live progress) ---------------------------------
    if start_verify_worker is None:
        start_verify_worker = _make_default_verify_worker(
            decoded,
            xpub_str,
            max_fee_rate_satskb=max_fee_rate_satskb,
            network=wallet.network,
        )
    verify = VerifyProposalScreen(
        proposal=decoded,
        account_xpub_str=xpub_str,
        network=wallet.network,
        max_fee_rate_satskb=max_fee_rate_satskb,
        start_worker=start_verify_worker,
    )
    run_screen(display, input_mgr, verify, target_fps=target_fps, idle_wake=idle_wake)
    if verify.result is None:
        return "stay"

    verified = verify.result

    # ---- 5. Show summary + confirm -------------------------------------
    confirm = ConfirmProposalScreen(
        proposal=decoded,
        account_xpub_str=xpub_str,
        verified=verified,
        network=wallet.network,
        max_fee_rate_satskb=max_fee_rate_satskb,
    )
    run_screen(
        display, input_mgr, confirm, target_fps=target_fps, idle_wake=idle_wake
    )
    if confirm.result != "sign":
        return "stay"

    # ---- 6. Sign --------------------------------------------------------
    derive_key = lambda b, i: vault.derive_signing_key(pin, wallet.id, b, i)  # noqa: E731
    try:
        signed = sgn.build_signed_tx(verified, derive_key)
    except sgn.SigningError as exc:
        log.exception("bonnet sign failed")
        _show_modal(
            display,
            title="Sign failed",
            body=str(exc)[:96],
            accent=COLOR_DANGER,
            hold_seconds=toast_seconds,
        )
        return "stay"

    # ---- 7. Animate signed_tx envelope back to companion ---------------
    signed_env = sgn.to_signed_envelope(signed, wallet_fp=fp)
    signed_blob = env.encode(signed_env)
    # 120-char chunks match the pairing flow: a typical signed BSV tx
    # is ~600–1500 bytes encoded which gives 6–12 frames at version-6
    # QR density (4 px/module on the 240 panel). Larger chunks would
    # shrink each module below the threshold a phone autofocus can
    # lock from arm's length.
    # 100-char chunks + ~10-char header = ~110 bytes/frame → QR version 7
    # (45×45 modules).  At the 200 px QR target that gives 4 px/module,
    # which is the minimum a phone autofocus through TFT glow can reliably
    # lock on.  (120-char chunks pushed frames to version 10 at 3 px/module
    # which was the root cause of companion scanning failures.)
    pw1_lines = split_envelope_to_lines(signed_blob, max_encoded_chunk_chars=100)
    qr = PairingMultipartQrScreen(
        pw1_lines,
        title="Signed tx",
        **qr_brightness_screen_kwargs(
            settings,
            settings_path=settings_path,
            on_settings_changed=on_settings_changed,
        ),
    )
    run_screen(display, input_mgr, qr, target_fps=target_fps, idle_wake=idle_wake)
    return "stay"


__all__ = [
    "ConfirmProposalScreen",
    "ScanProposalScreen",
    "SignFlowResult",
    "VerifyProposalScreen",
    "run_sign_flow",
]
