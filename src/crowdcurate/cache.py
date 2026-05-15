from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from .model import SlideItem


class ImageCache:
    def __init__(self, max_size: int = 3) -> None:
        self.max_size = max_size
        self._cache: dict[int, Image.Image] = {}

    def get(self, index: int) -> Image.Image | None:
        return self._cache.get(index)

    def set(self, index: int, image: Image.Image) -> None:
        self._cache[index] = image
        self._prune_old_entries(index)

    def load(self, slide: SlideItem) -> Image.Image:
        return Image.open(slide.source)

    def _prune_old_entries(self, current_index: int) -> None:
        if len(self._cache) <= self.max_size:
            return

        to_remove = []
        for idx in self._cache:
            distance = abs(idx - current_index)
            if distance > self.max_size:
                to_remove.append(idx)

        for idx in to_remove:
            del self._cache[idx]

    def clear(self) -> None:
        self._cache.clear()
