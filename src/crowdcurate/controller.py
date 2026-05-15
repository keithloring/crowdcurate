from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .cache import ImageCache
from .model import SlideDeck

if TYPE_CHECKING:
    from .view import SlideshowView


class SlideshowController:
    def __init__(
        self, deck: SlideDeck, view: "SlideshowView", interval_seconds: float = 5.0
    ) -> None:
        self.deck = deck
        self.view = view
        self.interval_seconds = interval_seconds
        self._playing = False
        self._after_id: Any | None = None
        self._preload_id: Any | None = None
        self.cache = ImageCache(max_size=3)
        self.view.set_controller(self)

    @property
    def is_playing(self) -> bool:
        return self._playing

    def show_current(self) -> None:
        slide = self.deck.get_current()
        if slide is None:
            self.view.show_placeholder(
                "No images were found in the selected directories."
            )
            self.view.update_status("No slides available")
            return
        image = self.cache.get(self.deck.current_index)
        if image is None:
            image = self.cache.load(slide)
            self.cache.set(self.deck.current_index, image)
        self.view.display_slide(slide, image)
        self.view.update_status(self.deck.current_status())
        self._schedule_preload()

    def next_slide(self) -> None:
        slide = self.deck.move_next()
        if slide is None:
            self.view.show_placeholder(
                "No images were found in the selected directories."
            )
            self.view.update_status("No slides available")
            return
        image = self.cache.get(self.deck.current_index)
        if image is None:
            image = self.cache.load(slide)
            self.cache.set(self.deck.current_index, image)
        self.view.display_slide(slide, image)
        self.view.update_status(self.deck.current_status())
        self._schedule_preload()
        if self._playing:
            self._schedule_next()

    def previous_slide(self) -> None:
        slide = self.deck.move_previous()
        if slide is None:
            self.view.show_placeholder(
                "No images were found in the selected directories."
            )
            self.view.update_status("No slides available")
            return
        image = self.cache.get(self.deck.current_index)
        if image is None:
            image = self.cache.load(slide)
            self.cache.set(self.deck.current_index, image)
        self.view.display_slide(slide, image)
        self.view.update_status(self.deck.current_status())
        self._schedule_preload()
        if self._playing:
            self._schedule_next()

    def toggle_playback(self) -> None:
        if self._playing:
            self.stop()
            return
        if self.deck.size == 0:
            self.view.show_placeholder(
                "No images were found in the selected directories."
            )
            self.view.update_status("No slides available")
            return
        self._playing = True
        self.view.update_play_button(self._playing)
        self._schedule_next()

    def stop(self) -> None:
        if self._after_id is not None:
            self.view.cancel_scheduled(self._after_id)
            self._after_id = None
        self._playing = False
        self.view.update_play_button(self._playing)

    def _schedule_next(self) -> None:
        if self._after_id is not None:
            self.view.cancel_scheduled(self._after_id)
        self._after_id = self.view.schedule(self.interval_seconds, self.next_slide)

    def _schedule_preload(self) -> None:
        if self._preload_id is not None:
            self.view.cancel_scheduled(self._preload_id)
        self._preload_id = self.view.schedule(0.1, self._preload_adjacent_images)

    def _preload_adjacent_images(self) -> None:
        for offset in [1, -1]:
            try:
                idx = (self.deck.current_index + offset) % self.deck.size
                if self.cache.get(idx) is None:
                    adj_slide = self.deck.slides[idx]
                    image = self.cache.load(adj_slide)
                    self.cache.set(idx, image)
            except (IndexError, OSError):
                pass
        self._preload_id = None
