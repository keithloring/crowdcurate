"""Core slide model for the slideshow deck."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

from dataclasses import dataclass

SUPPORTED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tiff",
}


@dataclass(frozen=True)
class SlideItem:
    """A single slide item backed by a file path."""

    source: Path

    @property
    def extension(self) -> str:
        """Return the lowercase file extension for the source file."""
        return self.source.suffix.lower()

    @property
    def is_image(self) -> bool:
        """Return True when the file type is a supported image."""
        return self.extension in SUPPORTED_IMAGE_EXTENSIONS


class SlideDeck:
    """A deck of slides with indexing and navigation helpers."""

    def __init__(self, paths: Iterable[Path] | None = None) -> None:
        """Create a deck, optionally populated from one or more directories."""
        self._slides: list[SlideItem] = []
        self._seen_paths: set[Path] = set()
        self.current_index = 0
        if paths is not None:
            self.add_directories(paths)

    @property
    def slides(self) -> tuple[SlideItem, ...]:
        """Return the slides in a tuple for read-only access."""
        return tuple(self._slides)

    @property
    def size(self) -> int:
        """Return the number of slides in the deck."""
        return len(self._slides)

    def add_directories(self, paths: Iterable[Path]) -> None:
        """Add slides from each provided directory path."""
        for path in paths:
            self.add_directory(path)

    def add_directory(self, path: Path) -> None:
        """Add all supported image files found under a directory."""
        candidate = path.expanduser().resolve()
        if not candidate.exists():
            message = f"Path does not exist: {candidate}"
            raise FileNotFoundError(message)

        if candidate.is_file():
            self._add_file(candidate)
            return

        for file_path in sorted(candidate.rglob("*")):
            if file_path.is_file():
                self._add_file(file_path)

    def _add_file(self, file_path: Path) -> None:
        """Add a file to the deck when it is an image and not a duplicate."""
        slide = SlideItem(file_path)
        if not slide.is_image:
            return

        resolved = file_path.resolve()
        if resolved in self._seen_paths:
            return

        self._slides.append(slide)
        self._seen_paths.add(resolved)

    def get_current(self) -> SlideItem | None:
        """Return the currently selected slide, if any."""
        if not self._slides:
            return None
        return self._slides[self.current_index]

    def move_next(self) -> SlideItem | None:
        """Advance to the next slide and return it."""
        if not self._slides:
            return None
        self.current_index = (self.current_index + 1) % len(self._slides)
        return self.get_current()

    def move_previous(self) -> SlideItem | None:
        """Move to the previous slide and return it."""
        if not self._slides:
            return None
        self.current_index = (self.current_index - 1) % len(self._slides)
        return self.get_current()

    def jump_to(self, index: int) -> SlideItem | None:
        """Jump directly to the requested slide index."""
        if not self._slides:
            return None
        self.current_index = max(0, min(index, len(self._slides) - 1))
        return self.get_current()

    def reset(self) -> None:
        """Reset the deck to the first slide."""
        self.current_index = 0

    def current_status(self) -> str:
        """Return a human-readable status line for the current slide."""
        slide = self.get_current()
        if slide is None:
            return "No slides available"
        return f"{self.current_index + 1}/{len(self._slides)} — {slide.source.name}"
