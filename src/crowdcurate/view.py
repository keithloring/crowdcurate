from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Any, Callable

from PIL import Image, ImageTk

from .metadata import MetadataWindow
from .model import SlideItem

if TYPE_CHECKING:
    from .controller import SlideshowController

ScheduleCallback = Callable[[], None]


class SlideshowView:  # pylint: disable=too-many-instance-attributes
    def __init__(
        self, title: str = "CrowdCurate", size: tuple[int, int] = (1024, 768)
    ) -> None:
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry(f"{size[0]}x{size[1]}")
        self.root.minsize(640, 480)

        self._controller: Any | None = None
        self._current_photo: ImageTk.PhotoImage | None = None
        self._current_slide: SlideItem | None = None

        self.content_frame = ttk.Frame(self.root)
        self.content_frame.pack(expand=True, fill="both", padx=10, pady=10)

        self.main_area = ttk.Frame(self.content_frame)
        self.main_area.pack(side="left", expand=True, fill="both")

        self.metadata_window = MetadataWindow(self.content_frame)
        self.metadata_window.show(before_widget=self.main_area)

        self.info_header = ttk.Label(
            self.main_area,
            anchor="w",
            text="",
            wraplength=1000,
            font=("Segoe UI", 12, "bold"),
        )
        self.info_header.pack(fill="x", pady=(0, 10))

        self.image_frame = ttk.Frame(self.main_area)
        self.image_frame.pack(expand=True, fill="both")

        self.image_label = ttk.Label(
            self.image_frame, anchor="center", text="Loading..."
        )
        self.image_label.pack(expand=True, fill="both")

        self.controls_frame = ttk.Frame(self.main_area)
        self.controls_frame.pack(fill="x", padx=10, pady=10)

        self.buttons = {
            "previous": ttk.Button(
                self.controls_frame, text="Previous", command=self._on_previous
            ),
            "play": ttk.Button(
                self.controls_frame, text="Play", command=self._on_play_pause
            ),
            "next": ttk.Button(self.controls_frame, text="Next", command=self._on_next),
            "quit": ttk.Button(
                self.controls_frame, text="Quit", command=self.root.quit
            ),
        }

        self.buttons["previous"].pack(side="left")
        self.buttons["play"].pack(side="left", padx=6)
        self.buttons["next"].pack(side="left")
        self.buttons["quit"].pack(side="right")

        self.status_label = ttk.Label(self.root, anchor="w", text="Ready")
        self.status_label.pack(fill="x", padx=10, pady=(0, 10))

        self.root.bind("<Left>", lambda event: self._on_previous())
        self.root.bind("<Right>", lambda event: self._on_next())
        self.root.bind("<space>", lambda event: self._on_play_pause())
        self.root.bind("<Escape>", lambda event: self.root.quit())
        self.root.bind("<i>", lambda event: self._on_info())
        self.root.bind(
            "<Control-Shift-KeyPress-plus>",
            lambda event: self.metadata_window.increase_font_size(),
        )
        self.root.bind(
            "<Control-Shift-KeyPress-equal>",
            lambda event: self.metadata_window.increase_font_size(),
        )
        self.root.bind(
            "<Control-Shift-KeyPress-minus>",
            lambda event: self.metadata_window.decrease_font_size(),
        )
        self.root.bind(
            "<Control-KeyPress-KP_Add>",
            lambda event: self.metadata_window.increase_font_size(),
        )
        self.root.bind(
            "<Control-KeyPress-KP_Subtract>",
            lambda event: self.metadata_window.decrease_font_size(),
        )

    def set_controller(self, controller: "SlideshowController") -> None:
        self._controller = controller

    def display_slide(self, slide: SlideItem, image: Image.Image) -> None:
        if not slide.source.exists():
            self.show_placeholder("Image not found")
            return

        self._current_slide = slide
        self.metadata_window.update(slide)
        info_text = (
            f"File: {slide.source.name}  |  Path: {slide.source}  |  "
            f"SHA256: {self.metadata_window.current_hash or ''}"
        )
        self.info_header.config(text=info_text)
        resized_image = self._resize_image(image)
        self._current_photo = ImageTk.PhotoImage(resized_image)
        self.image_label.config(image=self._current_photo, text="")

    def show_placeholder(self, text: str) -> None:
        self.image_label.config(
            image="",
            text=text,
            anchor="center",
            font=("Segoe UI", 16),
            justify="center",
        )
        self._current_photo = None
        self.info_header.config(text="")
        self.metadata_window.clear()

    def update_status(self, text: str) -> None:
        self.status_label.config(text=text)

    def update_play_button(self, playing: bool) -> None:
        label = "Pause" if playing else "Play"
        self.buttons["play"].config(text=label)

    def schedule(self, delay_seconds: float, callback: ScheduleCallback) -> Any:
        return self.root.after(int(delay_seconds * 1000), callback)

    def cancel_scheduled(self, after_id: Any) -> None:
        if after_id is not None:
            self.root.after_cancel(after_id)

    def run(self) -> None:
        self.root.mainloop()

    def _resize_image(self, image: Image.Image) -> Image.Image:
        self.root.update_idletasks()
        width = (
            self.image_frame.winfo_width()
            or self.main_area.winfo_width()
            or self.root.winfo_width()
            or 800
        )
        height = (
            self.image_frame.winfo_height()
            or self.main_area.winfo_height()
            or self.root.winfo_height()
            or 600
        )
        width = max(1, width)
        height = max(1, height)

        ratio = min(width / image.width, height / image.height, 1.0)
        new_size = (
            max(1, int(image.width * ratio)),
            max(1, int(image.height * ratio)),
        )
        return image.resize(new_size, Image.Resampling.LANCZOS)

    def _on_previous(self) -> None:
        if self._controller is not None:
            self._controller.previous_slide()

    def _on_next(self) -> None:
        if self._controller is not None:
            self._controller.next_slide()

    def _on_play_pause(self) -> None:
        if self._controller is not None:
            self._controller.toggle_playback()

    def _on_info(self) -> None:
        self.metadata_window.toggle(
            self._current_slide,
            before_widget=self.main_area,
        )
