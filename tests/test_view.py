import os

import pytest

from crowdcurate.view import SlideshowView


def test_controls_frame_is_bottom_packed() -> None:
    if "DISPLAY" not in os.environ:
        pytest.skip("Tkinter requires a display to verify widget packing")

    view = SlideshowView()
    view.root.withdraw()
    try:
        view.root.update_idletasks()
        pack_info = view.controls_frame.pack_info()

        assert pack_info["side"] == "bottom"
        assert pack_info["fill"] == "x"
    finally:
        view.root.destroy()


def test_size_is_close_tolerates_small_changes() -> None:
    assert SlideshowView._size_is_close(None, (100, 100), (103, 98))
    assert SlideshowView._size_is_close(None, (200, 100), (206, 103))
    assert not SlideshowView._size_is_close(None, (100, 100), (130, 100))


def test_on_jump_to_prompts_for_current_index(monkeypatch) -> None:
    if "DISPLAY" not in os.environ:
        pytest.skip("Tkinter requires a display to verify widget prompts")

    prompts = []

    def fake_askinteger(title, prompt, parent, minvalue, maxvalue, initialvalue):
        prompts.append((title, prompt, minvalue, maxvalue, initialvalue))
        return 4

    monkeypatch.setattr("crowdcurate.view.simpledialog.askinteger", fake_askinteger)

    class DummyDeck:
        size = 5
        current_index = 2

    class DummyController:
        def __init__(self) -> None:
            self.deck = DummyDeck()
            self.jumped_to = None

        def jump_to(self, index: int) -> None:
            self.jumped_to = index

    view = SlideshowView()
    controller = DummyController()
    view.set_controller(controller)
    try:
        view._on_jump_to()
        assert prompts
        _, prompt_text, minvalue, maxvalue, initialvalue = prompts[0]
        assert "Enter slide number (1-5, current 3):" in prompt_text
        assert minvalue == 1
        assert maxvalue == 5
        assert initialvalue == 3
        assert controller.jumped_to == 3
    finally:
        view.root.destroy()
