"""Touch shell loop: icon grid, then a keyboard when the action needs text."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from piwallet.core.settings import BonnetSettings, load_settings
from piwallet.core.vault import Vault, VaultError, VaultWipedError, WrongPinError
from piwallet.touch.create import CreateFlow, PinPad
from piwallet.touch.input import ScriptedTouch, Tap
from piwallet.touch.manage import ManageFlow
from piwallet.touch.restore import RestoreFlow
from piwallet.touch.settings import SettingsFlow
from piwallet.ui.display import COLOR_BG, Display, FrameBuffer
from piwallet.touch.ui import AlphabetKeyboard, IconGrid, WalletHome


class TouchRestart(Exception):
    """Diagnostics confirmed a restart. The CLI relaunches this process."""


def relaunch_process() -> None:
    """Replace this process with the same command line."""
    os.execvp(sys.argv[0], sys.argv)


def run_touch_shell(
    display: Display,
    touch: ScriptedTouch,
    *,
    vault: Vault | None = None,
    camera_rotation: int = 0,
    hardware: tuple[tuple[str, str], ...] = (),
    target_fps: int = 60,
    max_iterations: int | None = None,
    sleep: bool = True,
    settings_path: Path | None = None,
    splash: bool | None = None,
    disclaimer: bool | None = None,
    terms_path: Path | None = None,
) -> str | None:
    """Run the icon home until the loop cap hits.

    Returns the last accepted word or name. On the panel this loops
    until Ctrl-C. A still screen is not repainted: the loop only polls
    touch, and a frame goes out when a finger or the screen changes.
    ``target_fps`` is how often that poll happens.
    """
    home = IconGrid(display.width, display.height)
    menu = WalletHome(display.width, display.height) if vault is not None else None
    keyboard: AlphabetKeyboard | None = None
    pin_pad: PinPad | None = None
    pin: str | None = None
    creating: CreateFlow | None = None
    restoring: RestoreFlow | None = None
    managing: ManageFlow | None = None
    settings_flow: SettingsFlow | None = None
    prefs = load_settings(settings_path)
    display.set_brightness(prefs.brightness)
    camera_rotation = 0 if camera_rotation is None else camera_rotation
    show_splash = max_iterations is None if splash is None else splash
    if show_splash:
        from piwallet.core.paths import default_vault_path
        from piwallet.touch.splash import run_touch_splash

        if run_touch_splash(display, touch, sleep=sleep) == "diagnostics":
            from piwallet.touch.factory_menu import run_touch_diagnostics

            diag_vault = vault if vault is not None else Vault(default_vault_path())
            if (
                run_touch_diagnostics(
                    display,
                    touch,
                    diag_vault,
                    camera_rotation=camera_rotation,
                    sleep=sleep,
                )
                == "restart"
            ):
                raise TouchRestart()
    show_terms = max_iterations is None if disclaimer is None else disclaimer
    if show_terms:
        from piwallet.core.paths import default_terms_path
        from piwallet.firstboot.terms import mark_accepted, requires_acceptance
        from piwallet.touch.disclaimer import run_touch_disclaimer

        terms = terms_path if terms_path is not None else default_terms_path()
        if requires_acceptance(terms):
            run_touch_disclaimer(display, touch, sleep=sleep)
            mark_accepted(terms)
    last_activity = time.monotonic()
    blanked = False
    locked = False
    pending_new_pin: str | None = None
    accepted: str | None = None
    if vault is not None:
        creating_pin = not vault.exists
        pin_pad = PinPad(
            display.width,
            display.height,
            title="Create PIN" if creating_pin else "Enter PIN",
            masked=not creating_pin,
        )
    fb = FrameBuffer(width=display.width, height=display.height)
    poll_s = 1.0 / max(1, target_fps)
    iterations = 0
    dirty = True
    while True:
        if max_iterations is not None and iterations >= max_iterations:
            break
        iterations += 1
        started = time.monotonic()
        tap = touch.poll()
        now = time.monotonic()
        if blanked:
            if tap is not None:
                blanked = False
                last_activity = now
                tap = None
                dirty = True
                if locked:
                    locked = False
                    pin_pad = PinPad(
                        display.width,
                        display.height,
                        title="Enter PIN",
                        masked=True,
                    )
        elif tap is not None:
            last_activity = now
        elif prefs.sleep_timeout_ms > 0 and now - last_activity >= prefs.sleep_timeout_ms / 1000:
            blanked = True
            dirty = True
            if pin is not None and vault is not None and vault.exists:
                locked = True
                pin = None
        if tap is not None and pin_pad is not None:
            pin_pad.on_tap(tap)
            if pin_pad.result:
                entered = pin_pad.result
                pin_pad.grid.down = None
                creating_new = vault is not None and not vault.exists
                if creating_new and pending_new_pin is None:
                    pending_new_pin = entered
                    pin_pad = PinPad(
                        display.width,
                        display.height,
                        title="Confirm PIN",
                        masked=False,
                    )
                    pin_pad.message = "Enter it again"
                    pin_pad.message_error = False
                elif creating_new and entered != pending_new_pin:
                    pending_new_pin = None
                    pin_pad = PinPad(
                        display.width,
                        display.height,
                        title="Create PIN",
                        masked=False,
                    )
                    pin_pad.message = "PINs do not match"
                    pin_pad.message_error = True
                else:
                    pin_pad.message = "Checking PIN..."
                    pin_pad.message_error = False
                    pin_pad.draw(fb)
                    display.flip(fb)
                    try:
                        pin = _accept_pin(vault, entered)
                    except WrongPinError as exc:
                        pin_pad.digits = ""
                        pin_pad.result = None
                        pin_pad.message = f"Wrong PIN. {exc.attempts_remaining} left"
                        pin_pad.message_error = True
                    except VaultWipedError:
                        pin_pad.digits = ""
                        pin_pad.result = None
                        pin_pad.message = "Too many tries. Vault wiped"
                        pin_pad.message_error = True
                    except VaultError as exc:
                        pin_pad.digits = ""
                        pin_pad.result = None
                        pin_pad.message = str(exc)
                        pin_pad.message_error = True
                    else:
                        pending_new_pin = None
                        pin_pad = None
        elif tap is not None and creating is not None:
            creating.on_tap(tap)
            if creating.done:
                if creating.label:
                    accepted = creating.label
                    if menu is not None:
                        menu.message = ""
                    else:
                        home.status = creating.label
                elif creating.error:
                    text = creating.error[:22]
                    if menu is not None:
                        menu.message = text
                    else:
                        home.status = text
                creating = None
        elif tap is not None and restoring is not None:
            restoring.on_tap(tap)
            if restoring.done:
                if restoring.label and menu is not None:
                    menu.message = ""
                elif restoring.error and menu is not None:
                    menu.message = restoring.error[:22]
                restoring = None
        elif tap is not None and keyboard is not None:
            keyboard.on_tap(tap)
            if keyboard.done:
                accepted = keyboard.result
                if keyboard.result:
                    home.status = keyboard.result
                keyboard = None
        elif tap is not None and managing is not None:
            managing.on_tap(tap)
            if managing.done:
                managing = None
        elif tap is not None and settings_flow is not None:
            settings_flow.on_tap(tap)
            prefs = settings_flow.settings
            if settings_flow.done:
                vault, pin, pin_pad, settings_flow, prefs = _leave_settings(
                    settings_flow, vault, display
                )
        elif tap is not None and menu is not None and pin is not None:
            menu.set_wallets(vault.list_wallets() if vault is not None else [])
            action = menu.on_tap(tap)
            if action == "add":
                creating = CreateFlow(
                    display.width,
                    display.height,
                    vault,
                    pin,
                    camera_rotation=camera_rotation,
                )
            elif action == "restore":
                restoring = RestoreFlow(display.width, display.height, vault, pin)
            elif action == "settings" and vault is not None:
                settings_flow = SettingsFlow(
                    display.width,
                    display.height,
                    vault,
                    pin,
                    display=display,
                    settings=prefs,
                    settings_path=settings_path,
                    hardware=hardware,
                )
            elif action is not None and vault is not None:
                wallet = next((item for item in menu.wallets if item.id == action), None)
                if wallet is not None:
                    menu.message = ""
                    managing = ManageFlow(display.width, display.height, vault, pin, wallet)
                    managing._camera_rotation = camera_rotation
        elif tap is not None:
            action = home.on_tap(tap)
            if action == "new":
                keyboard = AlphabetKeyboard(
                    display.width, display.height, mode="name", title="Wallet name"
                )
            elif action == "restore":
                keyboard = AlphabetKeyboard(
                    display.width, display.height, mode="word", title="Restore word"
                )
            elif action == "wallets":
                home.status = "No wallets"
            elif action is not None:
                home.status = action
        if creating is not None and creating.tick():
            dirty = True
        if managing is not None and managing.tick():
            dirty = True
        if settings_flow is not None and settings_flow.tick():
            dirty = True
        if tap is not None:
            dirty = True
        if dirty:
            if menu is not None and pin is not None and vault is not None and settings_flow is None:
                menu.set_wallets(vault.list_wallets())
            if blanked:
                fb.clear(COLOR_BG)
            elif pin_pad is not None:
                pin_pad.draw(fb)
            elif creating is not None:
                creating.draw(fb)
            elif restoring is not None:
                restoring.draw(fb)
            elif keyboard is not None:
                keyboard.draw(fb)
            elif managing is not None:
                managing.draw(fb)
            elif settings_flow is not None:
                settings_flow.draw(fb)
            elif menu is not None and pin is not None:
                menu.draw(fb)
            else:
                home.draw(fb)
            display.flip(fb)
            dirty = False
        if sleep:
            remaining = poll_s - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)
    return accepted


def _leave_settings(
    flow: SettingsFlow,
    vault: Vault | None,
    display: Display,
) -> tuple[Vault | None, str | None, PinPad | None, None, BonnetSettings]:
    """Apply a finished settings visit and return to the wallet list or PIN."""
    pin = flow.new_pin or flow.pin
    pin_pad = None
    if flow.restored and flow.new_pin:
        if vault is not None:
            vault = Vault(vault.path)
        pin = flow.new_pin
    elif flow.factory_reset or flow.wiped or flow.restored:
        if vault is not None:
            vault = Vault(vault.path)
        pin = None
        creating = vault is None or not vault.exists
        pin_pad = PinPad(
            flow.width,
            flow.height,
            title="Create PIN" if creating else "Enter PIN",
            masked=not creating,
        )
        if flow.restored:
            pin_pad.message = "Enter the backup PIN"
        else:
            pin_pad.message = "Create a new PIN"
        pin_pad.message_error = False
    display.set_brightness(flow.settings.brightness)
    return vault, pin, pin_pad, None, flow.settings


def _accept_pin(vault: Vault | None, pin: str) -> str:
    if vault is None:
        return pin
    if not vault.exists:
        vault.create(pin)
        return pin
    vault.check_pin(pin)
    return pin


def tap_at(hit_xy: tuple[int, int], *, pressed: bool = True) -> Tap:
    return Tap(hit_xy[0], hit_xy[1], pressed)
