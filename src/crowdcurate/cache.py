# ruff: noqa: D100, D101, D102

from __future__ import annotations

import contextlib
import queue
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from PIL import Image, ImageTk

if TYPE_CHECKING:
    from pathlib import Path

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


class ThumbnailCache:
    """Threaded thumbnail cache that loads PIL images in background.

    ImageTk.PhotoImage objects are generated on the Tk main thread.

    Usage:
      thumb = thumbnail_cache.get_photo(path, max_size=(120,80), on_ready=callback)
    If the photo is already cached the ImageTk.PhotoImage is returned. Otherwise
    a lightweight placeholder is returned and the background loader will call
    `on_ready(path, photo)` on the Tk main thread when available.
    """

    def __init__(
        self,
        root: tk.Misc | None = None,
        max_workers: int = 4,
        placeholder_size: tuple[int, int] = (120, 80),
    ) -> None:
        self.root = root
        self._cache: dict[str, ImageTk.PhotoImage] = {}
        self._loading: set[str] = set()
        self._pending_callbacks: dict[str, list[object]] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._queue: queue.Queue[
            tuple[
                str, Path, Image.Image | None, ImageTk.PhotoImage | None, object | None
            ]
        ] = queue.Queue()
        self._queue_flush_scheduled = False
        self._placeholder = Image.new("RGB", placeholder_size, (220, 220, 220))
        self._placeholder_cache: dict[str, ImageTk.PhotoImage] = {}

    def _make_placeholder(self) -> ImageTk.PhotoImage | None:
        if self.root is None:
            return None
        with contextlib.suppress(AttributeError, RuntimeError, TypeError, ValueError):
            return ImageTk.PhotoImage(self._placeholder.copy())
        return None

    def _schedule_queue_flush(self) -> None:
        if (
            self.root is None
            or not self.root.winfo_exists()
            or self._queue_flush_scheduled
        ):
            return
        self._queue_flush_scheduled = True
        with contextlib.suppress(AttributeError, RuntimeError, tk.TclError, TypeError):
            self.root.after(0, self._drain_queue)
        self._queue_flush_scheduled = False

    def _drain_queue(self) -> None:
        self._queue_flush_scheduled = False
        while True:
            try:
                key, path, img, placeholder, on_ready = self._queue.get_nowait()
            except queue.Empty:
                break
            photo = placeholder
            try:
                if img is not None:
                    photo = ImageTk.PhotoImage(img)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                photo = placeholder
            with self._lock:
                self._cache[key] = photo
                self._loading.discard(key)
                self._placeholder_cache.pop(key, None)
                pending = self._pending_callbacks.pop(key, [])
            callbacks = []
            if on_ready is not None:
                callbacks.append(on_ready)
            callbacks.extend(pending)
            for callback in callbacks:
                with contextlib.suppress(
                    AttributeError, RuntimeError, TypeError, ValueError
                ):
                    callback(path, photo)
        if (
            not self._queue.empty()
            and self.root is not None
            and self.root.winfo_exists()
        ):
            self._schedule_queue_flush()

    def shutdown(self) -> None:
        with contextlib.suppress(AttributeError, RuntimeError, ValueError, OSError):
            self._executor.shutdown(wait=True, cancel_futures=True)

    def get_photo(
        self,
        path: Path,
        max_size: tuple[int, int] = (120, 80),
        on_ready: object | None = None,
    ) -> ImageTk.PhotoImage | None:
        key = str(path)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            if key in self._loading:
                if on_ready is not None:
                    self._pending_callbacks.setdefault(key, []).append(on_ready)
                return self._placeholder_cache.get(key)
            placeholder = self._make_placeholder()
            if placeholder is not None:
                self._placeholder_cache[key] = placeholder
            self._loading.add(key)

        def _load() -> None:
            try:
                img = Image.open(path)
                img.thumbnail(max_size, Image.Resampling.LANCZOS)
            except (OSError, RuntimeError, TypeError, ValueError):
                img = None
            self._queue.put((key, path, img, placeholder, on_ready))
            self._schedule_queue_flush()

        self._executor.submit(_load)
        return placeholder

    def get_thumbnail(
        self, slide: SlideItem, max_size: tuple[int, int] = (160, 160)
    ) -> Image.Image:
        try:
            img = Image.open(slide.source)
        except (OSError, ValueError):
            return Image.new("RGB", max_size, (200, 200, 200))
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        return img
