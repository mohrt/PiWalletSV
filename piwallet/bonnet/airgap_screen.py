"""Bonnet "Airgap status" diagnostic screen.

Presents the result of :func:`piwallet.diag.airgap.check_airgap` as a
green-or-red headline plus a six-row check table. Reachable from the
Settings menu's ``Airgap status`` action row.

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
B PRESS    Back to Settings.
B LONG     Exit the bonnet app entirely.
=========  ==================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from piwallet.diag.airgap import AirgapReport, check_airgap
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DIM,
    COLOR_FG,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    FrameBuffer,
)
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.widgets import draw_text

AirgapScreenResult = Literal["back", "exit"]

# Reserve dedicated colours for the airgap verdict — they need to read
# at a glance, distinct from accent (used for titles in other screens).
COLOR_OK = (96, 192, 96)
COLOR_FAIL = (224, 80, 80)


@dataclass
class AirgapScreen:
    """Read-only diagnostic screen showing the live airgap report."""

    report: AirgapReport = field(default_factory=check_airgap)
    done: bool = False
    result: AirgapScreenResult | None = None

    # -- input -------------------------------------------------------

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if b == Button.B and k == EventKind.LONG:
            self.done = True
            self.result = "exit"
            return
        if b == Button.B and k == EventKind.PRESS:
            self.done = True
            self.result = "back"
            return
        if b in (Button.A, Button.SELECT) and k == EventKind.PRESS:
            # Refresh in place. The next draw() reflects the new report.
            # Cheap (subprocess + a few sysfs reads) so we don't need a
            # spinner.
            self.report = check_airgap()

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

        # Six rows, one per check. Status glyph on the right, coloured
        # to match the row's verdict — cursor highlight isn't needed,
        # this is a read-only screen.
        y = title_h + 14
        row_step = 22
        for c in self.report.checks:
            row_color = (
                COLOR_OK
                if c.ok is True
                else COLOR_FAIL
                if c.ok is False
                else COLOR_DIM
            )
            draw_text(
                fb, 12, y, c.name, size=12, color=COLOR_FG, anchor="lm"
            )
            draw_text(
                fb,
                DISPLAY_WIDTH - 12,
                y,
                c.status,
                size=12,
                color=row_color,
                anchor="rm",
            )
            y += row_step

        # Footer: refresh hint + sandbox note. The sandbox note is the
        # operator's reminder that the interfaces row is sandbox-only;
        # they should also run ``piwallet diag airgap`` from a shell to
        # verify the host.
        if self.report.inconclusive:
            note = f"{len(self.report.inconclusive)} check(s) n/a"
            note_color = COLOR_DIM
        else:
            note = "shell: piwallet diag airgap"
            note_color = COLOR_ACCENT
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 24,
            note,
            size=10,
            color=note_color,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 10,
            "A refresh   B back   hold B quit",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
