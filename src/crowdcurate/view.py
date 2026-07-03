from __future__ import annotations

import shlex
import subprocess
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import TYPE_CHECKING, Any, Callable

from PIL import Image, ImageTk

from .metadata import ExifEditorWindow, MetadataWindow
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
        self._current_image_original: Image.Image | None = None
        self._resize_after_id: Any | None = None
        self._allow_upscale: bool = True

        self.controls_frame = ttk.Frame(self.root)
        self.controls_frame.pack(side="bottom", fill="x", padx=10, pady=10)

        self.content_frame = ttk.Frame(self.root)
        self.content_frame.pack(expand=True, fill="both", padx=10, pady=10)

        self.main_area = ttk.Frame(self.content_frame)
        self.main_area.pack(side="left", expand=True, fill="both")

        self.metadata_window = MetadataWindow(self.content_frame)
        self.metadata_window.show(before_widget=self.main_area)

        self.image_frame = ttk.Frame(self.main_area)
        self.image_frame.pack(expand=True, fill="both")

        self.image_label = ttk.Label(
            self.image_frame, anchor="center", text="Loading..."
        )
        self.image_label.pack(expand=True, fill="both")
        # Right-click (Button-3) on the image to show Open With menu
        self.image_label.bind("<Button-3>", self._on_image_right_click)

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
        # Refresh current image after external edit with 'r'
        self.root.bind("r", lambda event: self._on_refresh())
        # Edit EXIF/IPTC metadata with 'x'
        self.root.bind("x", lambda event: self._on_edit_exif())
        # Show help with '?' or F1
        self.root.bind("?", lambda event: self._on_help())
        self.root.bind("<F1>", lambda event: self._on_help())
        # Re-render the current image after window resizing (debounced)
        self.root.bind("<Configure>", self._on_configure)
        # Toggle upscaling on/off with 'u'
        self.root.bind("u", lambda event: self._toggle_upscale())
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
        self._current_image_original = image
        self.metadata_window.update(slide)
        # Use centralized refresh to size and display the image
        self._refresh_current_image()

    def show_placeholder(self, text: str) -> None:
        self.image_label.config(
            image="",
            text=text,
            anchor="center",
            font=("Segoe UI", 16),
            justify="center",
        )
        self._current_photo = None
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
        # Choose the smaller scale to fill as much of the window as possible
        # (allow upscaling so one dimension fills the available space)
        ratio = min(width / image.width, height / image.height)
        new_size = (
            max(1, int(image.width * ratio)),
            max(1, int(image.height * ratio)),
        )
        return image.resize(new_size, Image.Resampling.LANCZOS)

    def _refresh_current_image(self) -> None:
        """Resize and display the currently loaded original image."""
        if self._current_image_original is None:
            return
        try:
            resized_image = self._resize_image(self._current_image_original)
            self._current_photo = ImageTk.PhotoImage(resized_image)
            self.image_label.config(image=self._current_photo, text="")
        except (OSError, tk.TclError):
            # If anything goes wrong re-show placeholder to avoid crashing UI
            self.show_placeholder("Image not found")

    def _on_configure(self, _event: object) -> None:
        # Debounce configure events so we don't thrash image resizing
        if self._resize_after_id is not None:
            try:
                self.root.after_cancel(self._resize_after_id)
            except tk.TclError:
                pass
        self._resize_after_id = self.root.after(100, self._on_configure_idle)

    def _toggle_upscale(self) -> None:
        """Toggle whether images are allowed to be upscaled to fill the window."""
        self._allow_upscale = not self._allow_upscale
        prev = self.status_label.cget("text")
        state_text = "Upscale: On" if self._allow_upscale else "Upscale: Off"
        self.status_label.config(text=state_text)
        # restore previous status after a short delay
        self.root.after(1500, lambda: self.status_label.config(text=prev))
        # refresh display to apply the new setting
        self.root.after_idle(self._refresh_current_image)

    def _on_configure_idle(self) -> None:
        self._resize_after_id = None
        self._refresh_current_image()

    def _on_previous(self) -> None:
        if self._controller is not None:
            self._controller.previous_slide()
            # ensure we re-render to maximize within the current window
            self.root.after_idle(self._refresh_current_image)

    def _on_next(self) -> None:
        if self._controller is not None:
            self._controller.next_slide()
            # ensure we re-render to maximize within the current window
            self.root.after_idle(self._refresh_current_image)

    def _on_play_pause(self) -> None:
        if self._controller is not None:
            self._controller.toggle_playback()

    def _on_info(self) -> None:
        # Toggle the info sidebar and refresh the image afterwards
        self.metadata_window.toggle(
            self._current_slide,
            before_widget=self.main_area,
        )
        self.root.after_idle(self._refresh_current_image)

    def _on_refresh(self) -> None:
        """Reload the current image from disk (use after editing externally)."""
        if self._controller is not None:
            try:
                self._controller.refresh_current()
                self.root.after_idle(self._refresh_current_image)
            except (OSError, RuntimeError):
                # If controller-refresh is unavailable or fails, attempt local refresh
                self.root.after_idle(self._refresh_current_image)

    def _on_help(self) -> None:
        """Show a simple help popup listing available keystrokes."""
        help_text = (
            "Keys:\n"
            "  Left / Right: Previous / Next slide\n"
            "  Space: Play / Pause\n"
            "  i: Toggle info sidebar\n"
            "  u: Toggle upscaling\n"
            "  r: Refresh current image (after external edit)\n"
            "  x: View/edit EXIF/IPTC/XMP metadata\n"
            "  ?: Show this help (also F1)\n"
            "  Ctrl+Shift +/-: Change metadata font size\n"
            "  Right-click image: Open with...\n"
        )
        messagebox.showinfo("Help - Keystrokes", help_text, parent=self.root)

    def _on_edit_exif(self) -> None:
        """Open the EXIF/IPTC editor for the current image."""
        if self._current_slide is None:
            messagebox.showinfo("EXIF Editor", "No image loaded.", parent=self.root)
            return
        ExifEditorWindow(self.root, self._current_slide.source)

    def _on_image_right_click(self, event: Any) -> None:
        """Show a popup menu with 'Open with' choices for the current image."""
        if self._current_slide is None:
            return

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(
            label="Open with GIMP",
            command=lambda: self._open_with_cmd("gimp"),
        )
        menu.add_command(
            label="Open with System Default",
            command=lambda: self._open_with_cmd("xdg-open"),
        )
        menu.add_separator()
        menu.add_command(label="Choose command...", command=self._open_with_custom)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()  # pylint: disable=consider-using-with

    def _open_with_custom(self) -> None:
        if self._current_slide is None:
            return
        prompt = (
            "Enter command to run. Use {file} where you want the filename to appear, "
            "or leave it out to append the filename."
        )
        cmd = simpledialog.askstring("Open with...", prompt, parent=self.root)
        if not cmd:
            return
        self._open_with_cmd(cmd)

    def _open_with_cmd(self, cmd: str) -> None:
        if self._current_slide is None:
            return
        path = str(self._current_slide.source)
        # If user provided a placeholder {file}, substitute it
        if "{file}" in cmd:
            cmd_filled = cmd.replace("{file}", path)
            args = shlex.split(cmd_filled)
        else:
            args = shlex.split(cmd) + [path]

        try:
            # pylint: disable=consider-using-with
            subprocess.Popen(
                args,
                shell=False,
                start_new_session=True,
            )  # noqa: S603  # pylint: disable=consider-using-with
        except FileNotFoundError:
            messagebox.showerror(
                "Command not found",
                f"Could not run: {args[0]}",
                parent=self.root,
            )
        except (OSError, ValueError) as exc:
            # pragma: no cover - runtime error reporting
            messagebox.showerror(
                "Error launching",
                str(exc),
                parent=self.root,
            )
