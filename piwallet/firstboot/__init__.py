"""First-boot flow: disclaimer acceptance + initial setup wiring.

The first time the Pi boots into the PiWalletSV app (or whenever the
canonical disclaimer version bumps), the user must walk through a
short multi-page disclaimer on the bonnet. Acceptance is recorded in a
small JSON state file so the prompt is one-shot per disclaimer version.

This package exposes:

* :mod:`piwallet.firstboot.terms`      - persistence + version policy.
* :mod:`piwallet.firstboot.disclaimer` - the bonnet ``Screen``.
"""

from piwallet.firstboot.disclaimer import (
    DEFAULT_DISCLAIMER_PAGES,
    DisclaimerScreen,
)
from piwallet.firstboot.terms import (
    CURRENT_TERMS_VERSION,
    TermsState,
    default_state_path,
    load_state,
    mark_accepted,
    requires_acceptance,
    save_state,
)

__all__ = [
    "CURRENT_TERMS_VERSION",
    "DEFAULT_DISCLAIMER_PAGES",
    "DisclaimerScreen",
    "TermsState",
    "default_state_path",
    "load_state",
    "mark_accepted",
    "requires_acceptance",
    "save_state",
]
