from __future__ import annotations

import hashlib
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from typing import TYPE_CHECKING, Any

from PIL import Image

if TYPE_CHECKING:
    from .model import SlideItem


class MetadataWindow:
    def __init__(self, parent: Any) -> None:
        self.parent = parent
        self.frame = ttk.Frame(self.parent, width=320)
        self._font_size = 12
        self._text_widget: tk.Text | None = None
        self.current_hash: str | None = None
        self._visible = False
        self._create_widgets()

    def _create_widgets(self) -> None:
        title_label = ttk.Label(
            self.frame,
            text="Image Details",
            font=("Segoe UI", 12, "bold"),
            anchor="w",
        )
        title_label.pack(fill="x", pady=(0, 8))

        self._text_widget = tk.Text(
            self.frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            width=40,
            height=20,
            borderwidth=0,
            highlightthickness=0,
        )
        self._text_widget.pack(expand=True, fill="both")
        self._apply_font_size()

        self.hide_button = ttk.Button(self.frame, text="Hide Info", command=self.hide)
        self.hide_button.pack(fill="x", pady=(10, 0))

    def show(
        self,
        slide: SlideItem | None = None,
        before_widget: tk.Widget | None = None,
    ) -> None:
        if not self._visible:
            pack_args = {
                "side": "left",
                "fill": "y",
                "padx": (0, 10),
                "pady": 0,
            }
            if before_widget is not None:
                pack_args["before"] = before_widget
            self.frame.pack(**pack_args)
            self._visible = True
        if slide is not None:
            self.update(slide)

    def hide(self) -> None:
        if self._visible:
            self.frame.pack_forget()
            self._visible = False

    def toggle(
        self,
        slide: SlideItem | None = None,
        before_widget: tk.Widget | None = None,
    ) -> None:
        if self._visible:
            self.hide()
        else:
            self.show(slide, before_widget=before_widget)

    def update(self, slide: SlideItem) -> None:
        if self._text_widget is None:
            return

        if slide.source.exists():
            self.current_hash = self._compute_sha256(slide.source)
        else:
            self.current_hash = None

        metadata = self._get_metadata(slide)
        self._text_widget.config(state=tk.NORMAL)
        self._text_widget.delete("1.0", tk.END)
        self._text_widget.insert(tk.END, metadata)
        self._text_widget.config(state=tk.DISABLED)

    def clear(self) -> None:
        if self._text_widget is None:
            return
        self._text_widget.config(state=tk.NORMAL)
        self._text_widget.delete("1.0", tk.END)
        self._text_widget.config(state=tk.DISABLED)
        self.current_hash = None

    def increase_font_size(self) -> str:
        self._font_size += 1
        self._apply_font_size()
        return "break"

    def decrease_font_size(self) -> str:
        self._font_size = max(6, self._font_size - 1)
        self._apply_font_size()
        return "break"

    def _apply_font_size(self) -> None:
        if self._text_widget is None:
            return
        current_font = tkfont.Font(family="Courier", size=self._font_size)
        self._text_widget.config(font=current_font)

    def _get_metadata(self, slide: SlideItem) -> str:
        lines = [
            "FILE DATA:",
        ]

        if slide.source.exists():
            stat = slide.source.stat()
            size_bytes = stat.st_size
            size_kb = size_bytes / 1024
            mod_time = datetime.fromtimestamp(stat.st_mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            lines.extend(
                [
                    f"Size: {size_bytes:,} bytes ({size_kb:.1f} KB)",
                    f"Modified: {mod_time}",
                ]
            )
        else:
            lines.append("File not found")

        lines.extend(["\nIMAGE DATA:"])

        try:
            image = Image.open(slide.source)
            lines.extend(
                [
                    f"Format: {image.format}",
                    f"Mode: {image.mode}",
                    f"Size: {image.width} x {image.height} pixels",
                ]
            )
        except (OSError, ValueError) as e:
            lines.append(f"Error reading image: {e}")

        return "\n".join(lines)

    @staticmethod
    def _compute_sha256(path: Path) -> str:
        sha256_hash = hashlib.sha256()
        with open(path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
