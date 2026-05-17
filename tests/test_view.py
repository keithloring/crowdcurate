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
