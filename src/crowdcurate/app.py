from __future__ import annotations

import argparse
from pathlib import Path

from .controller import SlideshowController
from .model import SlideDeck
from .view import SlideshowView


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="crowdcurate",
        description=(
            "Run a tkinter slideshow over image files in one " "or more directories."
        ),
    )
    parser.add_argument(
        "directories",
        nargs="*",
        default=["."],
        help=(
            "Directories to scan for images. Defaults to the "
            "current working directory."
        ),
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Seconds between automatic slide transitions when playback is enabled.",
    )
    parser.add_argument(
        "--title",
        default="CrowdCurate",
        help="Window title for the slideshow application.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    directories = [Path(path).expanduser() for path in args.directories]
    deck = SlideDeck(directories)
    view = SlideshowView(title=args.title)
    controller = SlideshowController(deck, view, args.interval)
    view.root.update_idletasks()
    controller.show_current()
    view.run()
    return 0
