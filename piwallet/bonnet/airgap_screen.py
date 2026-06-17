"""Bonnet "Airgap status" diagnostic screen.

Presents the result of :func:`piwallet.diag.airgap.check_airgap` as a
green-or-red headline plus three summary rows (**Wi-Fi**, **Bluetooth**,
**Network**). Reachable from Settings → **Maintenance** → **Airgap status**
row. Each row rolls up several technical checks (drivers, switches, apps,
startup config) so the operator only sees familiar labels.

Why this exists
---------------
PiWalletSV's whole pitch is "keys never leave the device". The
operator deserves a way to verify that claim is still holding before
they sign anything sensitive — without dropping to a shell, without
trusting the marketing copy. One click from the Settings screen
should answer the question "is this thing actually quiet on the
airwaves right now?".

Sandboxing caveat
-----------------
The bonnet runs with ``PrivateNetwork=yes``, so the
``check_no_network_interfaces`` row only sees ``lo`` regardless of
host config. That's still meaningful — it confirms the bonnet's
sandbox is intact — but for end-to-end host verification the operator
should also run ``piwallet diag airgap`` from a shell. The other five
rows (modules, rfkill, services, boot config, blacklist) see the host
truthfully through namespaced-but-unrestricted paths. The screen
flags the interfaces row appropriately so an operator reading "OK"
isn't misled.

Controls
--------
=========  ==================================================
A / SEL    Refresh — re-run all checks.
B          Back to Maintenance.
=========  ==================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from piwallet.diag.airgap import (
    AirgapReport,
    CheckResult,
    check_airgap,
    checks_for_bonnet_display,
)
from piwallet.ui.display import (
    COLOR_BG,
    COLOR_DIM,
    COLOR_FG,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    FrameBuffer,
)
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.widgets import draw_text

AirgapScreenResult = Literal["back"]

# Reserve dedicated colours for the airgap verdict — they need to read
# at a glance, distinct from accent (used for titles in other screens).
COLOR_OK = (96, 192, 96)
COLOR_FAIL = (224, 80, 80)


@dataclass
class AirgapScreen:
    """Read-only diagnostic screen showing the live airgap report."""

    report: AirgapReport = field(default_factory=check_airgap)
    _display_checks: tuple[CheckResult, ...] | None = field(
        default=None, repr=False
    )
    done: bool = False
    result: AirgapScreenResult | None = None

    def _refresh(self) -> None:
        self.report = check_airgap()
        self._display_checks = checks_for_bonnet_display()

    def _rows(self) -> tuple[CheckResult, ...]:
        if self._display_checks is None:
            self._display_checks = checks_for_bonnet_display()
        return self._display_checks

    # -- input -------------------------------------------------------

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if b == Button.B and k == EventKind.PRESS:
            self.done = True
            self.result = "back"
            return
        if b in (Button.A, Button.SELECT) and k == EventKind.PRESS:
            # Refresh in place. The next draw() reflects the new report.
            # Cheap (subprocess + a few sysfs reads) so we don't need a
            # spinner.
            self._refresh()

    # -- render ------------------------------------------------------

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        title_h = 28

        # Header band: green or red depending on the verdict, so the
        # answer is readable from across the room before any text is
        # processed.
        verdict_color = COLOR_OK if self.report.ok else COLOR_FAIL
        fb.draw.rectangle(
            (0, 0, DISPLAY_WIDTH, title_h),
            fill=(20, 20, 32),
            outline=verdict_color,
        )
        headline = "Air-gapped" if self.report.ok else "BREACH"
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            title_h // 2,
            headline,
            size=14,
            color=verdict_color,
            anchor="mm",
        )

        # Wi-Fi, Bluetooth, and Network — one row each.
        y = title_h + 28
        row_step = 32
        for c in self._rows():
            row_color = (
                COLOR_OK
                if c.ok is True
                else COLOR_FAIL
                if c.ok is False
                else COLOR_DIM
            )
            draw_text(
                fb, 12, y, c.display_name, size=12, color=COLOR_FG, anchor="lm"
            )
            draw_text(
                fb,
                DISPLAY_WIDTH - 12,
                y,
                c.bonnet_status,
                size=12,
                color=row_color,
                anchor="rm",
            )
            y += row_step

        # Footer: refresh hint; inconclusive count when some checks could
        # not run (no shell/CLI reference — keep the LCD self-contained).
        footer_y = DISPLAY_HEIGHT - 10
        if self.report.inconclusive:
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                DISPLAY_HEIGHT - 24,
                f"{len(self.report.inconclusive)} check(s) n/a",
                size=10,
                color=COLOR_DIM,
                anchor="mm",
            )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            footer_y,
            "A refresh   B back",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
