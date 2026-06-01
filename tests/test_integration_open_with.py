# pylint: disable=protected-access

import os
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from crowdcurate.model import SlideItem
from crowdcurate.view import SlideshowView


def test_open_with_cmds_integration(monkeypatch, tmp_path: Path) -> None:
    if "DISPLAY" not in os.environ:
        pytest.skip("Tkinter requires a display to verify integration")

    img = tmp_path / "img.jpg"
    Image.new("RGB", (10, 10)).save(img, format="JPEG")

    view = SlideshowView()
    view.root.withdraw()
    try:
        view._current_slide = SlideItem(img)

        called = []

        class DummyPopen:
            def __init__(self, args, _shell=False, **_kwargs):
                called.append(list(args))

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        monkeypatch.setattr(subprocess, "Popen", DummyPopen)

        # basic command appends filename
        view._open_with_cmd("gimp")
        assert called[-1] == ["gimp", str(img)]

        # system default opener
        view._open_with_cmd("xdg-open")
        assert called[-1] == ["xdg-open", str(img)]

        # command with placeholder
        view._open_with_cmd("gimp {file}")
        assert called[-1] == ["gimp", str(img)]

        # simple command like echo
        view._open_with_cmd("echo")
        assert called[-1] == ["echo", str(img)]
    finally:
        view.root.destroy()
