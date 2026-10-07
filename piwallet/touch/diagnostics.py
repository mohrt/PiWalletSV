"""Back-compat name for the touch factory menu.

The boot path imports :mod:`piwallet.touch.factory_menu`. This module
re-exports the same entry points.
"""

from piwallet.touch.factory_menu import DiagnosticsFlow, run_touch_diagnostics

__all__ = ["DiagnosticsFlow", "run_touch_diagnostics"]
