from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

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
    source: Path

    @property
    def extension(self) -> str:
        return self.source.suffix.lower()

    @property
    def is_image(self) -> bool:
        return self.extension in SUPPORTED_IMAGE_EXTENSIONS


class SlideDeck:
    def __init__(self, paths: Iterable[Path] | None = None) -> None:
        self._slides: list[SlideItem] = []
        self._seen_paths: set[Path] = set()
        self.current_index = 0
        if paths is not None:
            self.add_directories(paths)

    @property
    def slides(self) -> tuple[SlideItem, ...]:
        return tuple(self._slides)

    @property
    def size(self) -> int:
        return len(self._slides)

    def add_directories(self, paths: Iterable[Path]) -> None:
        for path in paths:
            self.add_directory(path)

    def add_directory(self, path: Path) -> None:
        candidate = path.expanduser().resolve()
        if not candidate.exists():
            raise FileNotFoundError(f"Path does not exist: {candidate}")

        if candidate.is_file():
            self._add_file(candidate)
            return

        for file_path in sorted(candidate.rglob("*")):
            if file_path.is_file():
                self._add_file(file_path)

    def _add_file(self, file_path: Path) -> None:
        slide = SlideItem(file_path)
        if not slide.is_image:
            return

        resolved = file_path.resolve()
        if resolved in self._seen_paths:
            return

        self._slides.append(slide)
        self._seen_paths.add(resolved)

    def get_current(self) -> SlideItem | None:
        if not self._slides:
            return None
        return self._slides[self.current_index]

    def move_next(self) -> SlideItem | None:
        if not self._slides:
            return None
        self.current_index = (self.current_index + 1) % len(self._slides)
        return self.get_current()

    def move_previous(self) -> SlideItem | None:
        if not self._slides:
            return None
        self.current_index = (self.current_index - 1) % len(self._slides)
        return self.get_current()

    def jump_to(self, index: int) -> SlideItem | None:
        if not self._slides:
            return None
        self.current_index = max(0, min(index, len(self._slides) - 1))
        return self.get_current()

    def reset(self) -> None:
        self.current_index = 0

    def current_status(self) -> str:
        slide = self.get_current()
        if slide is None:
            return "No slides available"
        return f"{self.current_index + 1}/{len(self._slides)} — {slide.source.name}"
