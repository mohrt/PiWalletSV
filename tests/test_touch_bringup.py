"""Touch bring-up screen: held QR and tap coordinates, no joystick."""

from __future__ import annotations

from PIL import Image

from piwallet.device import framebuffer_for_panel, get_device, known_devices
from piwallet.touch.bringup import run_touch_bringup
from piwallet.touch.input import ScriptedTouch, Tap
from piwallet.ui.display import HeadlessDisplay, rgb_to_fb_bytes


def test_known_devices_include_zero_and_pi3() -> None:
    assert "zero" in known_devices()
    profile = get_device("pi3-ws35")
    assert profile.width == 480
    assert profile.height == 320
    assert profile.display == "framebuffer"
    assert profile.fb_device == "/dev/fb0"
    assert profile.swap_axes is True
    assert profile.invert_x is True
    assert profile.display_rotation_deg == 0
    assert profile.camera == "ov5647"
    assert profile.camera_rotation_deg is None
    panel_f = get_device("pi3-ws35f")
    assert panel_f.width == 320
    assert panel_f.height == 480
    assert panel_f.display == "framebuffer"
    assert panel_f.fb_device == "/dev/fb1"
    assert panel_f.swap_axes is False
    assert panel_f.invert_x is False
    assert panel_f.invert_y is False
    assert panel_f.camera == "ov5647"
    assert panel_f.camera_rotation_deg == 180
    zero = get_device("zero")
    assert zero.display == "st7789"
    assert zero.camera == "ov5647"
    assert zero.camera_rotation_deg == 90
    assert zero.display_rotation_deg == 180


def test_panel_framebuffer_follows_the_kernel_name(tmp_path) -> None:
    graphics = tmp_path / "graphics"
    (graphics / "fb0").mkdir(parents=True)
    (graphics / "fb0" / "name").write_text("panel-mipi-dbid\n", encoding="ascii")
    (graphics / "fb1").mkdir()
    (graphics / "fb1" / "name").write_text("vc4drmfb\n", encoding="ascii")
    assert framebuffer_for_panel("/dev/fb1", graphics_root=graphics) == "/dev/fb0"
    assert framebuffer_for_panel("/dev/fb1", graphics_root=tmp_path / "missing") == "/dev/fb1"


def test_bringup_paints_and_records_a_tap() -> None:
    display = HeadlessDisplay(width=480, height=320)
    touch = ScriptedTouch([Tap(12, 34, True), Tap(12, 34, False)])
    result = run_touch_bringup(
        display, touch, max_iterations=2, sleep=False, target_fps=10
    )
    assert result == Tap(12, 34, True)
    assert display.flip_count == 2
    # QR sits on a dark panel; the corner target is the accent/ok square.
    assert display.image.getpixel((0, 0)) == (0, 0, 0)
    assert display.image.getpixel((460, 20)) != (0, 0, 0)


def test_lcd_a_touch_puts_the_finger_back_on_its_tile() -> None:
    from piwallet.touch.input import map_touch

    # Raw X follows the glass Y. Raw Y follows the glass X, reversed.
    tiles = ((80, 80), (400, 80), (80, 240), (400, 240))
    for sx, sy in tiles:
        raw_x = int(sy / 320 * 4095)
        raw_y = int((480 - sx) / 480 * 4095)
        px, py = map_touch(
            raw_x, raw_y, width=480, height=320, xmin=0, xmax=4095, ymin=0, ymax=4095,
            swap_axes=True, invert_x=True, invert_y=False,
        )
        assert abs(px - sx) <= 2
        assert abs(py - sy) <= 2


def test_touch_reports_a_press_once_until_release() -> None:
    from piwallet.touch.input import take_press_edge

    emit, was = take_press_edge(False, True)
    assert emit is True
    emit, was = take_press_edge(was, True)
    assert emit is False
    emit, was = take_press_edge(was, False)
    assert (emit, was) == (True, False)


def test_wallet_home_lists_wallets_under_the_top_actions() -> None:
    from piwallet.core.vault import WalletRecord
    from piwallet.touch.ui import WalletHome
    from piwallet.ui.display import FrameBuffer

    home = WalletHome(480, 320)
    fb = FrameBuffer(width=480, height=320)
    home.draw(fb)
    assert home.hit("add").y1 < 48
    assert home.hit("restore").y1 < 48
    assert home.hit("settings").y1 < 48
    assert any(fb.image.getpixel((x, 140))[0] > 80 for x in range(480))
    home.set_wallets(
        [
            WalletRecord(
                id="w1",
                label="daily",
                fingerprint=bytes.fromhex("cf987d8c"),
                derivation_path="m/44'/236'/0'",
                word_count=12,
                created_at="2026-01-01T00:00:00Z",
            )
        ]
    )
    row = home.hit("w1")
    assert row.y0 > home.hit("add").y1
    home.on_tap(Tap(*row.center(), True))
    home.on_tap(Tap(*row.center(), False))
    add = home.hit("add")
    home.on_tap(Tap(add.center()[0], add.center()[1], True))
    home.on_tap(Tap(add.center()[0], add.center()[1] + 24, True))
    assert home.on_tap(Tap(add.center()[0], add.center()[1] + 24, False)) == "add"


def test_wallet_home_scrolls_when_the_list_is_taller_than_the_screen() -> None:
    from piwallet.core.vault import WalletRecord
    from piwallet.touch.ui import WalletHome
    from piwallet.ui.display import COLOR_ACCENT, FrameBuffer

    def record(n: int) -> WalletRecord:
        return WalletRecord(
            id=f"w{n}",
            label=f"wallet-{n}",
            fingerprint=bytes.fromhex("cf987d8c"),
            derivation_path="m/44'/236'/0'",
            word_count=12,
            created_at="2026-01-01T00:00:00Z",
        )

    home = WalletHome(480, 320)
    home.set_wallets([record(n) for n in range(8)])
    assert home.hit("w0").y0 < 80
    try:
        home.hit("w7")
    except KeyError:
        pass
    else:
        raise AssertionError("last wallet should start off screen")
    fb = FrameBuffer(width=480, height=320)
    home.draw(fb)
    assert fb.image.getpixel((470, 80)) == COLOR_ACCENT
    home.on_tap(Tap(200, 250, True))
    home.on_tap(Tap(200, 100, True))
    home.on_tap(Tap(200, 100, False))
    try:
        home.hit("w7")
    except KeyError:
        pass
    else:
        raise AssertionError("dragging the list should not scroll")
    bar_x = 464
    home.on_tap(Tap(bar_x, 300, True))
    home.on_tap(Tap(bar_x, 300, False))
    assert home.hit("w7").y0 > home.hit("add").y1


def test_portrait_home_shows_eight_wallets_without_a_scrollbar() -> None:
    from piwallet.core.vault import WalletRecord
    from piwallet.touch.ui import AlphabetKeyboard, WalletHome
    from piwallet.ui.display import COLOR_FG, FrameBuffer

    def record(n: int) -> WalletRecord:
        return WalletRecord(
            id=f"w{n}",
            label=f"wallet-{n}",
            fingerprint=bytes.fromhex("cf987d8c"),
            derivation_path="m/44'/236'/0'",
            word_count=12,
            created_at="2026-01-01T00:00:00Z",
            network="test" if n == 7 else "main",
        )

    home = WalletHome(320, 480)
    home.set_wallets([record(n) for n in range(8)])
    assert home.hit("w0").y0 > home.hit("add").y1
    assert home.hit("w7").y1 < 480
    assert home._bar_box() is None
    fb = FrameBuffer(width=320, height=480)
    home.draw(fb)
    row = home.hit("w7")
    # Network sits on the lower line of the row, inside the glass.
    assert any(fb.image.getpixel((row.x1 - 20, y))[0] > 180 for y in range(row.y0, row.y1))
    keyboard = AlphabetKeyboard(320, 480, mode="word", title="Restore word")
    assert keyboard.hit("a").x1 - keyboard.hit("a").x0 == keyboard.hit("q").x1 - keyboard.hit("q").x0
    for extra in ("1", " ", "-", "_"):
        try:
            keyboard.hit(extra)
        except KeyError:
            pass
        else:
            raise AssertionError(extra)
    keyboard.draw(fb)
    cx, cy = keyboard.hit("back").center()
    assert any(
        fb.image.getpixel((x, y)) == COLOR_FG
        for y in range(cy - 8, cy + 9)
        for x in range(cx - 12, cx + 13)
    )
    keyboard.text = "a"
    boxes = keyboard._suggestion_boxes()
    assert boxes
    assert all(x1 <= 320 for _x0, _y0, x1, _y1, _word in boxes)
    assert boxes[0][1] >= 52
    assert boxes[0][3] <= keyboard.hit("q").y0
    assert keyboard.hit("ok").y1 <= 480


def test_icon_grid_draws_a_mark_in_every_tile() -> None:
    from piwallet.touch.ui import IconGrid
    from piwallet.ui.display import COLOR_ACCENT, FrameBuffer

    grid = IconGrid(480, 320)
    fb = FrameBuffer(width=480, height=320)
    grid.draw(fb)
    for action_id in ("wallets", "new", "restore", "settings"):
        tile = grid.hit(action_id)
        found = False
        for y in range(tile.y0, tile.y1):
            for x in range(tile.x0, tile.x1):
                if fb.image.getpixel((x, y)) == COLOR_ACCENT:
                    found = True
                    break
            if found:
                break
        assert found, action_id


def test_icon_grid_opens_word_keyboard_and_accepts_a_bip39_word() -> None:
    from piwallet.touch.shell import run_touch_shell, tap_at
    from piwallet.touch.ui import AlphabetKeyboard, IconGrid

    display = HeadlessDisplay(width=480, height=320)
    grid = IconGrid(480, 320)
    keyboard = AlphabetKeyboard(480, 320, mode="word", title="Restore word")
    taps = []
    for point in (
        grid.hit("restore").center(),
        keyboard.hit("z").center(),
        keyboard.hit("o").center(),
        keyboard.hit("o").center(),
        keyboard.hit("ok").center(),
    ):
        taps.append(tap_at(point))
        taps.append(tap_at(point, pressed=False))
    result = run_touch_shell(
        display, ScriptedTouch(taps), max_iterations=len(taps), sleep=False
    )
    assert result == "zoo"


def test_name_keyboard_accepts_digits_space_and_punctuation() -> None:
    from piwallet.touch.ui import AlphabetKeyboard, IconGrid

    board = AlphabetKeyboard(480, 320, mode="name", title="Wallet name")
    assert board.hit("1").y1 <= board.hit("q").y0
    assert board.hit(" ").x1 - board.hit(" ").x0 > (board.hit("a").x1 - board.hit("a").x0) * 2
    cancel = board.hit("cancel")
    assert cancel.x0 > 300
    assert cancel.y1 < 40
    for ch in ("a", " ", "1", "-", "_"):
        point = board.hit(ch).center()
        board.on_tap(Tap(*point, True))
        board.on_tap(Tap(*point, False))
    board.on_tap(Tap(*board.hit("ok").center(), True))
    board.on_tap(Tap(*board.hit("ok").center(), False))
    assert board.result == "a 1-_"

    grid = IconGrid(480, 320, (("12", "12 words"), ("24", "24 words"), ("cancel", "Cancel")), show_icons=False)
    choice = grid.hit("cancel")
    assert choice.y1 < 40
    assert choice.x0 > 300
    assert grid.hit("12").y0 > choice.y1
    portrait = IconGrid(
        320,
        480,
        (("12", "12 words"), ("24", "24 words"), ("cancel", "Cancel")),
        show_icons=False,
    )
    button = portrait.hit("12")
    assert button.y1 - button.y0 == 56
    assert button.y1 < 160


def test_word_count_help_is_drawn_under_the_buttons(tmp_path) -> None:
    from piwallet.core.vault import Vault
    from piwallet.touch.create import CreateFlow
    from piwallet.ui.display import COLOR_DIM, FrameBuffer

    vault = Vault(tmp_path / "vault.bin")
    vault.create("123456")
    flow = CreateFlow(320, 480, vault, "123456")
    fb = FrameBuffer(width=320, height=480)
    flow.draw(fb)
    button = flow._count.hit("12")
    assert any(
        fb.image.getpixel((x, y)) == COLOR_DIM
        for y in range(button.y1 + 12, button.y1 + 48)
        for x in range(16, 280)
    )


def test_network_help_is_drawn_under_the_buttons(tmp_path) -> None:
    from piwallet.core.vault import Vault
    from piwallet.touch.create import CreateFlow
    from piwallet.ui.display import COLOR_DIM, FrameBuffer

    vault = Vault(tmp_path / "vault.bin")
    vault.create("123456")
    flow = CreateFlow(320, 480, vault, "123456")
    flow.phase = "network"
    fb = FrameBuffer(width=320, height=480)
    flow.draw(fb)
    button = flow._network_grid.hit("main")
    assert any(
        fb.image.getpixel((x, y)) == COLOR_DIM
        for y in range(button.y1 + 12, button.y1 + 48)
        for x in range(16, 280)
    )


def test_hd_path_help_is_under_the_buttons(tmp_path) -> None:
    from piwallet.core.vault import Vault
    from piwallet.touch.create import CreateFlow
    from piwallet.ui.display import COLOR_BG, COLOR_DIM, FrameBuffer

    vault = Vault(tmp_path / "vault.bin")
    vault.create("123456")
    flow = CreateFlow(320, 480, vault, "123456")
    flow.phase = "path"
    fb = FrameBuffer(width=320, height=480)
    flow.draw(fb)
    cancel = flow._path_grid.hit("cancel")
    button = flow._path_grid.hit("default")
    # The path string is only in the description, not a line above the buttons.
    assert all(
        fb.image.getpixel((x, y)) == COLOR_BG
        for y in range(cancel.y1 + 2, button.y0)
        for x in range(80, 200)
    )
    assert any(
        fb.image.getpixel((x, y)) == COLOR_DIM
        for y in range(button.y1 + 12, button.y1 + 48)
        for x in range(16, 280)
    )


def test_dice_entropy_mixes_the_rolls_into_the_phrase(monkeypatch) -> None:
    from piwallet.touch.create import CreateFlow
    from piwallet.ui.display import COLOR_BG, FrameBuffer

    seen: dict[str, object] = {}

    def _from_dice(rolls: list[int], word_count: int) -> str:
        seen["rolls"] = list(rolls)
        seen["count"] = word_count
        return "abandon " * 11 + "about"

    monkeypatch.setattr("piwallet.touch.create.mnemonic_from_dice_rolls", _from_dice)
    flow = CreateFlow(320, 480, vault=None, pin="123456")  # type: ignore[arg-type]
    flow._word_count = 12
    flow.phase = "dice"
    flow._rolls = [4, 2]
    fb = FrameBuffer(width=320, height=480)
    flow.draw(fb)
    boxes = flow._roll_boxes()
    assert len(boxes) == 48
    assert boxes[-1][3] <= 312
    assert boxes[-1][4] <= 480 - 56
    _index, x0, y0, x1, y1 = boxes[0]
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    assert any(
        fb.image.getpixel((cx + dx, cy + dy)) != COLOR_BG
        for dx in range(-8, 9)
        for dy in range(-10, 11)
    )
    _index, x0, y0, x1, y1 = boxes[2]
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    assert fb.image.getpixel((cx, cy)) == COLOR_BG
    flow._rolls = []
    face = next(item for item in flow._dice_hits() if item.id == "face:6")
    for _ in range(47):
        _tap(flow, face.center())
    assert flow.phase == "dice"
    assert flow._rolls == [6] * 47
    _tap(flow, face.center())
    assert flow.phase == "show"
    assert seen["count"] == 12
    assert seen["rolls"] == [6] * 48


def test_photo_entropy_uses_the_captured_jpeg(monkeypatch) -> None:
    from piwallet.touch.create import CreateFlow

    class _Cam:
        def __init__(self, **kwargs: object) -> None:
            self.rotation = kwargs.get("rotation_degrees")

        def open(self) -> None:
            return None

        def read_preview_rgb(self):
            import numpy as np

            return np.zeros((8, 8, 3), dtype=np.uint8)

        def capture_entropy_jpeg(self) -> bytes:
            return b"jpeg-bytes"

        def close(self) -> None:
            return None

    seen: dict[str, object] = {}

    def _from_jpeg(jpeg: bytes, word_count: int) -> str:
        seen["jpeg"] = jpeg
        seen["count"] = word_count
        return "abandon " * 11 + "about"

    monkeypatch.setattr("piwallet.touch.create.mnemonic_from_camera_jpeg", _from_jpeg)
    flow = CreateFlow(320, 480, vault=None, pin="123456", camera_rotation=180, camera_cls=_Cam)  # type: ignore[arg-type]
    flow._word_count = 12
    flow.phase = "photo"
    assert flow.tick() is True
    assert flow._photo is not None
    assert flow._photo.rotation == 180
    capture = next(item for item in flow._photo_hits() if item.id == "capture")
    _tap(flow, capture.center())
    assert flow.phase == "photo_ok"
    use = next(item for item in flow._photo_ok_hits() if item.id == "use")
    _tap(flow, use.center())
    assert seen == {"jpeg": b"jpeg-bytes", "count": 12}
    assert flow.phase == "show"


def test_phrase_page_clears_cancel_and_outlines_confirm(tmp_path) -> None:
    from piwallet.core.vault import Vault
    from piwallet.touch.create import CreateFlow
    from piwallet.ui.display import COLOR_ACCENT, COLOR_BG, COLOR_DIM, FrameBuffer

    vault = Vault(tmp_path / "vault.bin")
    vault.create("123456")
    flow = CreateFlow(320, 480, vault, "123456")
    flow.phase = "show"
    flow._words = ["abandon"] * 12
    fb = FrameBuffer(width=320, height=480)
    flow.draw(fb)
    from piwallet.touch.create import _line_size
    from piwallet.ui.widgets import text_bbox

    title = "Write these words down"
    size = _line_size(title, 320 - 116 - 24)
    title_w = text_bbox(title, size=size)[2] - text_bbox(title, size=size)[0]
    assert 12 + title_w < 320 - 116
    # First word row starts below the header Cancel button.
    assert all(fb.image.getpixel((x, 40)) == COLOR_BG for x in range(16, 180))
    bar_y = 480 - 48
    assert any(fb.image.getpixel((x, bar_y)) == COLOR_ACCENT for x in range(8, 300))
    # Tight rows, then the backup warning under the list.
    assert any(
        fb.image.getpixel((x, y)) == COLOR_DIM
        for y in range(56 + 6 * 32, 56 + 6 * 32 + 40)
        for x in range(16, 280)
    )


def test_wrong_confirm_word_shows_an_error(tmp_path) -> None:
    from piwallet.core.vault import Vault
    from piwallet.touch.create import CreateFlow
    from piwallet.ui.display import COLOR_DANGER, FrameBuffer

    vault = Vault(tmp_path / "vault.bin")
    vault.create("123456")
    flow = CreateFlow(320, 480, vault, "123456")
    flow._words = ["abandon"] * 12
    flow._index = 0
    flow._new_pool()
    flow.phase = "confirm"
    wrong = next(item.id for item in flow._confirm._hits if item.id not in ("abandon", "cancel"))
    tile = flow._confirm.hit(wrong)
    flow.on_tap(Tap(*tile.center(), True))
    flow.on_tap(Tap(*tile.center(), False))
    assert flow._confirm_error == "Wrong word. Try again."
    fb = FrameBuffer(width=320, height=480)
    flow.draw(fb)
    bottom = max(item.y1 for item in flow._confirm._hits if item.id != "cancel")
    assert any(
        fb.image.getpixel((x, y)) == COLOR_DANGER
        for y in range(bottom + 12, bottom + 36)
        for x in range(16, 280)
    )


def test_name_keyboard_rejects_a_blank_name() -> None:
    from piwallet.touch.ui import AlphabetKeyboard

    board = AlphabetKeyboard(320, 480, mode="name", title="Name")
    ok = board.hit("ok").center()
    board.on_tap(Tap(*ok, True))
    board.on_tap(Tap(*ok, False))
    assert board.done is False
    assert board.message == "Enter a name"
    board.text = "   "
    board.on_tap(Tap(*ok, True))
    board.on_tap(Tap(*ok, False))
    assert board.done is False
    assert board.result is None


def test_create_offers_the_companion_qr(tmp_path, monkeypatch) -> None:
    from piwallet.core.vault import Vault
    from piwallet.touch.create import CreateFlow
    from piwallet.touch.ui import AlphabetKeyboard

    phrase = "abandon " * 11 + "about"
    monkeypatch.setattr("piwallet.touch.create.generate", lambda _count: phrase)
    monkeypatch.setattr("piwallet.touch.create.pairing_pw1_lines", lambda *args, **kwargs: ["pw1-frame"])
    vault = Vault(tmp_path / "vault.bin")
    vault.create("123456")
    flow = CreateFlow(320, 480, vault, "123456")
    flow._words = phrase.split()
    flow._word_count = 12
    flow._name = AlphabetKeyboard(320, 480, mode="name", title="Wallet name")
    flow._name.text = "savings"
    flow.phase = "name"
    ok = flow._name.hit("ok").center()
    flow.on_tap(Tap(*ok, True))
    flow.on_tap(Tap(*ok, False))
    assert flow.phase == "pair"
    show = next(item for item in flow._pair_hits() if item.id == "show")
    flow.on_tap(Tap(*show.center(), True))
    flow.on_tap(Tap(*show.center(), False))
    assert flow.phase == "qr"
    assert flow._frames == ["pw1-frame"]
    done = next(item for item in flow._qr_hits() if item.id == "cancel")
    flow.on_tap(Tap(*done.center(), True))
    flow.on_tap(Tap(*done.center(), False))
    assert flow.done is True


def test_name_keyboard_accepts_free_text() -> None:
    from piwallet.touch.ui import AlphabetKeyboard
    from piwallet.ui.display import COLOR_ACCENT, FrameBuffer

    board = AlphabetKeyboard(320, 480, mode="name", title="Name")
    fb = FrameBuffer(width=320, height=480)
    board.draw(fb)
    key = board.hit("a")
    assert fb.image.getpixel((key.center()[0], key.y0)) == COLOR_ACCENT
    q, z = board.hit("q"), board.hit("z")
    assert (key.x1 - key.x0, key.y1 - key.y0) == (q.x1 - q.x0, q.y1 - q.y0)
    assert (key.x1 - key.x0, key.y1 - key.y0) == (z.x1 - z.x0, z.y1 - z.y0)
    assert key.x0 > q.x0
    assert z.x0 > key.x0
    board = AlphabetKeyboard(480, 320, mode="name", title="Name")
    for ch in ("a", "b", "ok"):
        point = board.hit(ch).center()
        board.on_tap(Tap(*point, True))
        assert board.down == ch
        board.on_tap(Tap(*point, False))
    assert board.done is True
    assert board.result == "ab"


def test_touch_create_wallet_saves_a_vault_record(tmp_path, monkeypatch) -> None:
    from piwallet.core.vault import Vault
    from piwallet.touch.create import CreateFlow
    from piwallet.touch.ui import AlphabetKeyboard

    phrase = "abandon " * 11 + "about"
    monkeypatch.setattr("piwallet.touch.create.generate", lambda _count: phrase)
    vault = Vault(tmp_path / "vault.bin")
    vault.create("123456")
    flow = CreateFlow(480, 320, vault, "123456")
    choice = flow._count.hit("12")
    flow.on_tap(Tap(*choice.center(), True))
    flow.on_tap(Tap(*choice.center(), False))
    assert flow.phase == "network"
    main = flow._network_grid.hit("main")
    flow.on_tap(Tap(*main.center(), True))
    flow.on_tap(Tap(*main.center(), False))
    assert flow.phase == "path"
    default = flow._path_grid.hit("default")
    flow.on_tap(Tap(*default.center(), True))
    flow.on_tap(Tap(*default.center(), False))
    assert flow.phase == "entropy"
    random = next(item for item in flow._entropy_hits() if item.id == "csr")
    flow.on_tap(Tap(*random.center(), True))
    flow.on_tap(Tap(*random.center(), False))
    assert flow.phase == "show"
    # All 12 words are on one page. Confirm advances.
    nxt = (360, 300)
    flow.on_tap(Tap(*nxt, True))
    flow.on_tap(Tap(*nxt, False))
    assert flow.phase == "confirm"
    for expected in phrase.split():
        assert flow._confirm is not None
        tile = flow._confirm.hit(expected)
        flow.on_tap(Tap(*tile.center(), True))
        flow.on_tap(Tap(*tile.center(), False))
    assert flow.phase == "name"
    board = flow._name
    assert isinstance(board, AlphabetKeyboard)
    for ch in "ab":
        point = board.hit(ch).center()
        flow.on_tap(Tap(*point, True))
        flow.on_tap(Tap(*point, False))
    ok = board.hit("ok").center()
    flow.on_tap(Tap(*ok, True))
    flow.on_tap(Tap(*ok, False))
    assert flow.phase == "pair"
    assert flow.done is False
    assert flow.label == "ab"
    skip = next(item for item in flow._pair_hits() if item.id == "skip")
    flow.on_tap(Tap(*skip.center(), True))
    flow.on_tap(Tap(*skip.center(), False))
    assert flow.done is True
    saved = vault.list_wallets()[0]
    assert saved.label == "ab"
    assert saved.network == "main"
    assert saved.derivation_path == "m/44'/236'/0'"


def test_pin_pad_shows_six_slots_while_typing() -> None:
    from piwallet.touch.create import PinPad
    from piwallet.ui.display import COLOR_ACCENT, COLOR_DIM, FrameBuffer

    pad = PinPad(480, 320, title="Create PIN")
    fb = FrameBuffer(width=480, height=320)
    pad.draw(fb)
    boxes = pad.slot_boxes()
    assert len(boxes) == 6
    for i, (x0, y0, x1, _y1) in enumerate(boxes):
        edge = fb.image.getpixel(((x0 + x1) // 2, y0))
        assert edge == (COLOR_ACCENT if i == 0 else COLOR_DIM)
    assert pad.grid.title == "Create PIN"
    assert pad.masked is False
    pad.on_tap(Tap(*pad.grid.hit("1").center(), True))
    pad.on_tap(Tap(*pad.grid.hit("1").center(), False))
    pad.draw(fb)
    x0, y0, x1, y1 = boxes[0]
    assert any(
        fb.image.getpixel((x, y))[0] > 180
        for x in range(x0 + 2, x1 - 2)
        for y in range(y0 + 2, y1 - 2)
    )


def test_pin_pad_shows_an_error_for_a_short_pin() -> None:
    from piwallet.touch.create import PinPad
    from piwallet.ui.display import COLOR_DANGER, COLOR_OK, FrameBuffer

    pad = PinPad(480, 320, title="Enter PIN", masked=True)
    pad.on_tap(Tap(*pad.grid.hit("1").center(), True))
    pad.on_tap(Tap(*pad.grid.hit("1").center(), False))
    pad.on_tap(Tap(*pad.grid.hit("ok").center(), True))
    pad.on_tap(Tap(*pad.grid.hit("ok").center(), False))
    assert pad.result is None
    assert pad.digits == "1"
    assert pad.message == "Enter all 6 digits"
    assert pad.grid.down is None
    fb = FrameBuffer(width=480, height=320)
    pad.draw(fb)
    assert any(
        fb.image.getpixel((x, y)) == COLOR_DANGER
        for y in range(64, 82)
        for x in range(480)
    )
    pad.message = "Checking PIN..."
    pad.message_error = False
    pad.draw(fb)
    assert any(
        fb.image.getpixel((x, y)) == COLOR_OK
        for y in range(64, 82)
        for x in range(480)
    )


def test_pin_pad_masks_digits_when_unlocking() -> None:
    from piwallet.touch.create import PinPad
    from piwallet.ui.display import FrameBuffer

    shown = PinPad(480, 320, title="Create PIN")
    hidden = PinPad(480, 320, title="Enter PIN", masked=True)
    shown.digits = "1"
    hidden.digits = "1"
    clear = FrameBuffer(width=480, height=320)
    masked = FrameBuffer(width=480, height=320)
    shown.draw(clear)
    hidden.draw(masked)
    assert hidden.grid.title == "Enter PIN"
    assert clear.image.tobytes() != masked.image.tobytes()


def test_touch_shell_opens_pin_pad_for_a_new_vault(tmp_path) -> None:
    from piwallet.core.vault import Vault
    from piwallet.touch.shell import run_touch_shell

    vault = Vault(tmp_path / "vault.bin")
    result = run_touch_shell(
        HeadlessDisplay(width=480, height=320),
        ScriptedTouch([]),
        vault=vault,
        max_iterations=1,
        sleep=False,
    )
    assert result is None
    assert vault.exists is False


def _pin_presses(width: int, height: int, digits: str) -> list[Tap]:
    from piwallet.touch.create import PinPad

    pad = PinPad(width, height, title="Create PIN")
    taps: list[Tap] = []
    for digit in digits:
        center = pad.grid.hit(digit).center()
        taps.append(Tap(center[0], center[1], True))
        taps.append(Tap(center[0], center[1], False))
    ok = pad.grid.hit("ok").center()
    taps.append(Tap(ok[0], ok[1], True))
    taps.append(Tap(ok[0], ok[1], False))
    return taps


def test_create_pin_asks_again_and_rejects_a_mismatch(tmp_path) -> None:
    from piwallet.core.vault import Vault
    from piwallet.touch.shell import run_touch_shell

    vault = Vault(tmp_path / "vault.bin")
    width, height = 320, 480
    first = _pin_presses(width, height, "123456")
    run_touch_shell(
        HeadlessDisplay(width=width, height=height),
        ScriptedTouch(first),
        vault=vault,
        max_iterations=len(first),
        sleep=False,
    )
    assert vault.exists is False

    mismatch = first + _pin_presses(width, height, "654321")
    run_touch_shell(
        HeadlessDisplay(width=width, height=height),
        ScriptedTouch(mismatch),
        vault=vault,
        max_iterations=len(mismatch),
        sleep=False,
    )
    assert vault.exists is False

    match = first + _pin_presses(width, height, "123456")
    run_touch_shell(
        HeadlessDisplay(width=width, height=height),
        ScriptedTouch(match),
        vault=vault,
        max_iterations=len(match),
        sleep=False,
    )
    assert vault.exists is True
    vault.check_pin("123456")


def test_touch_shell_repaints_on_a_tap_and_not_while_idle() -> None:
    from piwallet.touch.shell import run_touch_shell
    from piwallet.touch.ui import IconGrid

    display = HeadlessDisplay(width=480, height=320)
    run_touch_shell(display, ScriptedTouch([]), max_iterations=4, sleep=False)
    assert display.flip_count == 1
    grid = IconGrid(480, 320)
    press = Tap(*grid.hit("restore").center(), True)
    run_touch_shell(
        display,
        ScriptedTouch([press]),
        max_iterations=1,
        sleep=False,
    )
    assert display.flip_count == 2


def test_wallet_menu_matches_the_zero_choices() -> None:
    from piwallet.core.vault import WalletRecord
    from piwallet.touch.manage import ManageFlow
    from piwallet.ui.display import COLOR_ACCENT, COLOR_DIM, FrameBuffer

    wallet = WalletRecord(
        id="w1",
        label="daily",
        fingerprint=bytes.fromhex("cf987d8c"),
        derivation_path="m/44'/236'/0'",
        word_count=12,
        created_at="2026-01-01T00:00:00Z",
    )
    flow = ManageFlow(320, 480, vault=None, pin="123456", wallet=wallet)  # type: ignore[arg-type]
    labels = [item.id for item in flow._hits() if item.id != "cancel"]
    assert labels == ["receive", "companion", "sign", "info", "rename", "delete"]
    fb = FrameBuffer(width=320, height=480)
    flow.draw(fb)
    edge = flow.hit("receive")
    assert fb.image.getpixel((edge.center()[0], edge.y0)) == COLOR_ACCENT
    assert edge.y1 < flow.hit("delete").y0
    info = flow.hit("info")
    flow.on_tap(Tap(*info.center(), True))
    flow.on_tap(Tap(*info.center(), False))
    assert flow.phase == "info"
    flow.draw(fb)
    assert any(
        fb.image.getpixel((x, y)) == COLOR_DIM
        for y in range(56, 80)
        for x in range(16, 140)
    )
    cancel = flow.hit("cancel")
    flow.on_tap(Tap(*cancel.center(), True))
    flow.on_tap(Tap(*cancel.center(), False))
    assert flow.phase == "menu"
    sign = flow.hit("sign")
    flow.on_tap(Tap(*sign.center(), True))
    flow.on_tap(Tap(*sign.center(), False))
    assert flow.phase == "sign"
    flow.on_tap(Tap(*flow.hit("cancel").center(), True))
    flow.on_tap(Tap(*flow.hit("cancel").center(), False))
    assert flow.phase == "menu"
    erase = flow.hit("delete")
    flow.on_tap(Tap(*erase.center(), True))
    flow.on_tap(Tap(*erase.center(), False))
    assert flow.phase == "delete"
    flow.on_tap(Tap(*flow.hit("erase").center(), True))
    flow.on_tap(Tap(*flow.hit("erase").center(), False))
    assert flow.phase == "delete2"
    flow.on_tap(Tap(*flow.hit("cancel").center(), True))
    flow.on_tap(Tap(*flow.hit("cancel").center(), False))
    assert flow.phase == "menu"
    assert flow.done is False
    flow.on_tap(Tap(*flow.hit("cancel").center(), True))
    flow.on_tap(Tap(*flow.hit("cancel").center(), False))
    assert flow.done is True


def test_receive_screen_shows_the_next_address() -> None:
    from piwallet.core.derivation import derive_account, master_xprv_from_seed
    from piwallet.core.mnemonic import seed_from_mnemonic
    from piwallet.core.vault import WalletRecord
    from piwallet.touch.manage import ManageFlow
    from piwallet.ui.display import FrameBuffer

    phrase = " ".join(["abandon"] * 11 + ["about"])
    account = derive_account(master_xprv_from_seed(seed_from_mnemonic(phrase)))
    xpub = str(account.xpub)

    class _Vault:
        def get_account_xpub(self, pin: str, wallet_id: str) -> str:
            assert pin == "123456"
            assert wallet_id == "w1"
            return xpub

    wallet = WalletRecord(
        id="w1",
        label="daily",
        fingerprint=account.fingerprint,
        derivation_path=account.path,
        word_count=12,
        created_at="2026-01-01T00:00:00Z",
    )
    flow = ManageFlow(320, 480, _Vault(), "123456", wallet)  # type: ignore[arg-type]
    receive = flow.hit("receive")
    flow.on_tap(Tap(*receive.center(), True))
    flow.on_tap(Tap(*receive.center(), False))
    assert flow.phase == "receive"
    first = flow._address
    assert first.startswith("1")
    fb = FrameBuffer(width=320, height=480)
    flow.draw(fb)
    assert any(
        fb.image.getpixel((x, y)) != (0, 0, 0)
        for y in range(50, 100)
        for x in range(70, 250)
    )
    qr_x, _qr_y, side, brighter, dimmer = flow._qr_layout()
    assert brighter.x0 >= qr_x + side
    assert dimmer.y0 > brighter.y1
    flow.on_tap(Tap(*brighter.center(), True))
    flow.on_tap(Tap(*brighter.center(), False))
    assert flow._qr_bg == 155
    assert flow._index == 0
    from piwallet.touch.manage import _address_size, _width

    assert _address_size(first, 320 - 16) == 14
    assert _width(first, 14) <= 320 - 16
    nxt = flow.hit("next")
    flow.on_tap(Tap(*nxt.center(), True))
    flow.on_tap(Tap(*nxt.center(), False))
    assert flow._index == 1
    assert flow._address != first
    prev = flow.hit("prev")
    flow.on_tap(Tap(*prev.center(), True))
    flow.on_tap(Tap(*prev.center(), False))
    assert flow._address == first


def _tap(flow, point: tuple[int, int]) -> None:
    flow.on_tap(Tap(*point, True))
    flow.on_tap(Tap(*point, False))


def test_restore_keeps_asking_until_the_phrase_is_complete() -> None:
    from piwallet.core.vault import WalletRecord
    from piwallet.touch.restore import RestoreFlow
    from piwallet.ui.display import COLOR_BG, COLOR_DANGER, COLOR_OK, FrameBuffer

    saved: dict[str, object] = {}

    class _Vault:
        def list_wallets(self) -> list[WalletRecord]:
            return []

        def add_wallet(self, pin: str, phrase: str, label: str, **kwargs: object) -> WalletRecord:
            saved["phrase"] = phrase
            saved["label"] = label
            saved["network"] = kwargs["network"]
            return WalletRecord(
                id="restored",
                label=label,
                fingerprint=bytes.fromhex("cf987d8c"),
                derivation_path="m/44'/236'/0'",
                word_count=12,
                created_at="2026-01-01T00:00:00Z",
            )

    flow = RestoreFlow(320, 480, _Vault(), "123456")  # type: ignore[arg-type]
    _tap(flow, flow._count.hit("12").center())
    _tap(flow, flow._network_grid.hit("main").center())
    _tap(flow, flow._path_grid.hit("default").center())
    assert flow.phase == "word"
    assert flow._keyboard is not None
    assert flow._keyboard.title == "Word 1 of 12"
    assert flow._keyboard.hit("prev").x1 <= flow._keyboard.hit("cancel").x0
    assert flow._keyboard.hit("prev").y0 < 40
    _tap(flow, flow._keyboard.hit("prev").center())
    assert flow.phase == "path"
    assert flow._keyboard is None
    _tap(flow, flow._path_grid.hit("default").center())
    assert flow.phase == "word"
    assert flow._keyboard is not None
    _tap(flow, flow._keyboard.hit("ok").center())
    assert flow.phase == "word"
    flow._keyboard.text = "abandon"
    _tap(flow, flow._keyboard.hit("ok").center())
    assert flow.done is False
    assert flow.phase == "word"
    assert flow._keyboard is not None
    assert flow._keyboard.title == "Word 2 of 12"
    assert flow._words == ["abandon"]
    fb = FrameBuffer(width=320, height=480)
    flow.draw(fb)
    below = flow._keyboard.hit("ok").y1
    assert any(
        fb.image.getpixel((x, y)) != COLOR_BG
        for y in range(below + 8, below + 28)
        for x in range(12, 180)
    )
    _tap(flow, flow._keyboard.hit("prev").center())
    assert flow.phase == "word"
    assert flow._words == []
    assert flow._keyboard is not None
    assert flow._keyboard.title == "Word 1 of 12"
    assert flow._keyboard.text == ""
    flow._keyboard.text = "abandon"
    _tap(flow, flow._keyboard.hit("ok").center())
    assert flow._words == ["abandon"]
    assert flow._keyboard is not None
    assert flow._keyboard.title == "Word 2 of 12"
    phrase = ["abandon"] * 11 + ["about"]
    for word in phrase[1:]:
        assert flow._keyboard is not None
        flow._keyboard.text = word
        _tap(flow, flow._keyboard.hit("ok").center())
    assert flow.phase == "review"
    assert flow.checksum_ok()
    fb = FrameBuffer(width=320, height=480)
    flow.draw(fb)
    assert any(fb.image.getpixel((x, 12)) == COLOR_OK for x in range(12, 160))
    _tap(flow, next(item for item in flow._review_hits() if item.id == "save").center())
    assert flow.phase == "name"
    assert flow._keyboard is not None
    assert flow._keyboard.text == "restored-1"
    _tap(flow, flow._keyboard.hit("ok").center())
    assert flow.done is True
    assert flow.label == "restored-1"
    assert saved["phrase"] == " ".join(phrase)
    assert saved["network"] == "main"

    bad = RestoreFlow(320, 480, _Vault(), "123456")  # type: ignore[arg-type]
    bad._word_count = 12
    bad._words = ["abandon"] * 11 + ["zoo"]
    bad.phase = "review"
    assert bad.checksum_ok() is False
    assert all(item.id != "save" for item in bad._review_hits())
    bad.draw(fb)
    assert any(
        fb.image.getpixel((x, y)) == COLOR_DANGER
        for y in range(8, 28)
        for x in range(12, 220)
    )


def test_xpub_qr_cycles_and_returns_to_the_menu(monkeypatch) -> None:
    import time

    from piwallet.core.vault import VaultError, WalletRecord
    from piwallet.touch.manage import ManageFlow
    from piwallet.ui.display import COLOR_BG, FrameBuffer

    seen: dict[str, int] = {}

    def _lines(_vault, _pin, _wallet, chunk_chars: int = 100):
        seen["chunk"] = chunk_chars
        return ["PW1|one", "PW1|two"]

    monkeypatch.setattr("piwallet.touch.manage.pairing_pw1_lines", _lines)
    wallet = WalletRecord(
        id="w1",
        label="daily",
        fingerprint=bytes.fromhex("cf987d8c"),
        derivation_path="m/44'/236'/0'",
        word_count=12,
        created_at="2026-01-01T00:00:00Z",
    )
    flow = ManageFlow(320, 480, object(), "123456", wallet)  # type: ignore[arg-type]
    _tap(flow, flow.hit("companion").center())
    assert flow.phase == "companion"
    assert seen["chunk"] == 400
    assert flow._frames == ["PW1|one", "PW1|two"]
    assert flow._frame == 0
    fb = FrameBuffer(width=320, height=480)
    flow.draw(fb)
    qr_x, qr_y, side, brighter, _dimmer = flow._qr_layout()
    assert side > 200
    assert brighter.x0 >= qr_x + side
    assert any(
        fb.image.getpixel((x, y)) != COLOR_BG
        for y in range(qr_y + 8, qr_y + 40)
        for x in range(qr_x + 8, qr_x + side - 8)
    )
    flow._frame_at = time.monotonic() - 1
    assert flow.advance_qr() is True
    assert flow._frame == 1
    _tap(flow, brighter.center())
    assert flow._frame == 0
    assert flow._qr_bg == 155
    _tap(flow, flow.hit("cancel").center())
    assert flow.phase == "menu"
    assert flow._frames == []

    def _fail(_vault, _pin, _wallet, chunk_chars: int = 100):
        raise VaultError("locked")

    monkeypatch.setattr("piwallet.touch.manage.pairing_pw1_lines", _fail)
    _tap(flow, flow.hit("companion").center())
    assert flow.phase == "menu"
    assert flow.message == "locked"


def test_sign_scan_shows_the_camera_and_frame_count() -> None:
    from PIL import Image

    from piwallet.touch.sign import SignScan
    from piwallet.ui.display import COLOR_OK, FrameBuffer

    def start(state) -> None:
        state.latest_thumb = Image.new("RGB", (30, 20), (255, 0, 0))
        state.parts_received = 2
        state.parts_total = 5

    scan = SignScan(320, 480, start_worker=start)
    assert scan.poll() is True
    assert scan.status()[0] == "frame 2 / 5"
    fb = FrameBuffer(width=320, height=480)
    scan.draw(fb)
    assert any(
        fb.image.getpixel((x, y)) == (255, 0, 0)
        for y in range(44, 440)
        for x in range(8, 312)
    )
    scan.state.parts_received = 5
    scan.state.finished = True
    assert scan.poll() is True
    assert scan.status() == ("frame 5 / 5", COLOR_OK)
    back = Tap(320 - 60, 16, True)
    scan.on_tap(back)
    scan.on_tap(Tap(320 - 60, 16, False))
    assert scan.cancelled is True
    assert scan.state.cancel_requested is True
    assert scan.leave is True


def test_sign_scan_leaves_the_camera_when_the_frames_are_in() -> None:
    from piwallet.touch.sign import SignScan

    def start(state) -> None:
        state.assembled = b"not-an-envelope"
        state.parts_received = 2
        state.parts_total = 2
        state.finished = True

    scan = SignScan(320, 480, start_worker=start)
    assert scan.poll() is True
    assert scan.phase != "scan"
    assert scan._thread is not None
    scan._thread.join(timeout=2)
    scan.poll()
    assert scan.phase == "error"


def test_sign_confirm_lists_send_fee_and_network() -> None:
    from piwallet.core.verify import VerifiedInput, VerifiedProposal
    from piwallet.core.vault import WalletRecord
    from piwallet.touch.sign import SignScan

    wallet = WalletRecord(
        id="w1",
        label="daily",
        fingerprint=bytes(4),
        derivation_path="m/44'/236'/0'",
        word_count=12,
        created_at="2026-01-01T00:00:00Z",
        network="test",
    )
    scan = SignScan(320, 480, start_worker=lambda _state: None, wallet=wallet)
    from bsv import P2PKH, to_base58_check
    from bsv.constants import ADDRESS_TESTNET_PREFIX

    test_addr = to_base58_check(list(b"\x11" * 20), prefix=list(ADDRESS_TESTNET_PREFIX))
    pay_script = P2PKH().lock(test_addr).hex()
    scan.phase = "confirm"
    scan._verified = VerifiedProposal(
        inputs=(VerifiedInput("ab" * 32, 0, "76a91400", 1500, (0, 0)),),
        outputs=((pay_script, 1000), ("52", 400)),
        change_index=1,
        change_derivation=(1, 0),
        locktime=0,
    )
    assert scan.destinations() == [test_addr]
    assert scan.summary() == [
        ("Send", "1,000 sat"),
        ("Fee", "100 sat"),
        ("Net", "testnet"),
    ]
    assert any(item.id == "accept" for item in scan._hits())


def test_rgb565_pack_is_two_bytes_per_pixel() -> None:
    img = Image.new("RGB", (2, 1), (255, 0, 0))
    packed = rgb_to_fb_bytes(img, 16)
    assert packed == bytes((0x00, 0xF8, 0x00, 0xF8))
    packed32 = rgb_to_fb_bytes(img, 32)
    assert packed32 == bytes((0, 0, 255, 255, 0, 0, 255, 255))
