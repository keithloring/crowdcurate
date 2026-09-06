from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
from typing import Any

import tkinter as tk
from tkinter import filedialog, ttk, messagebox, simpledialog
from PIL import Image, ImageTk

from .model import SlideItem


@dataclass
class Sequence:
    name: str
    items: list[Path]
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "items": [str(p) for p in self.items],
            "created_at": self.created_at or datetime.utcnow().isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Sequence":
        items = [Path(p) for p in data.get("items", [])]
        return cls(name=data.get("name", "Unnamed"), items=items, created_at=data.get("created_at"))


class SequenceStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = (base_dir or Path.cwd()).expanduser().resolve() / ".sequences"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _safe_name(self, name: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        return safe or "sequence"

    def save(self, seq: Sequence) -> Path:
        filename = f"{self._safe_name(seq.name)}.json"
        dest = self.base_dir / filename
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(seq.to_dict(), fh, indent=2)
        return dest

    def load(self, name: str) -> Sequence | None:
        filename = f"{self._safe_name(name)}.json"
        path = self.base_dir / filename
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return Sequence.from_dict(data)

    def list(self) -> list[str]:
        return [p.stem for p in sorted(self.base_dir.glob("*.json"))]


class SequencePanel:
    """Minimal toggleable panel with two thumbnail rows and basic DnD.

    - Source row: shows thumbnails from provided slides (list of SlideItem)
    - Sequence row: shows current sequence; supports click-to-add, drag from source to sequence
      and reorder within sequence.

    This class is intentionally contained so view.py can import and instantiate it lazily.
    """

    def __init__(self, parent: tk.Widget, controller: Any) -> None:
        self.parent = parent
        self.controller = controller
        self.frame = ttk.Frame(self.parent)
        self._visible = False

        # canvases
        self._source_canvas: tk.Canvas | None = None
        self._sequence_canvas: tk.Canvas | None = None

        # image refs to avoid GC
        self._source_photos: list[ImageTk.PhotoImage] = []
        self._sequence_photos: list[ImageTk.PhotoImage] = []
        self._source_widgets: dict[str, tk.Label] = {}
        self._source_widget_ids: dict[str, int] = {}
        self._last_source_selection_key: str | None = None

        # drag state
        self._dragging = False
        self._drag_moved = False
        self._pending_drag_source: SlideItem | None = None
        self._drag_photo: ImageTk.PhotoImage | None = None
        self._drag_ghost: tk.Toplevel | None = None
        self._drag_source_path: Path | None = None
        self._drag_from_index: int | None = None

        self._create_widgets()

    def _create_widgets(self) -> None:
        toolbar = ttk.Frame(self.frame)
        toolbar.pack(fill="x", pady=(4, 4))
        ttk.Label(toolbar, text="Sequence Editor", font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Button(toolbar, text="Export MP4", command=self._export_sequence_video).pack(side="right")
        ttk.Button(toolbar, text="New", command=self._new_sequence).pack(side="right")
        ttk.Button(toolbar, text="Save", command=self._save_sequence).pack(side="right", padx=4)
        ttk.Button(toolbar, text="Clear", command=self._clear_sequence).pack(side="right", padx=4)

        ttk.Label(self.frame, text="Source Images").pack(fill="x")
        self._source_canvas = tk.Canvas(self.frame, height=100)
        src_scroll = ttk.Scrollbar(self.frame, orient="horizontal", command=self._source_canvas.xview)
        self._source_canvas.configure(xscrollcommand=src_scroll.set)
        self._source_canvas.pack(fill="x", expand=True)
        src_scroll.pack(fill="x")

        ttk.Label(self.frame, text="Sequence").pack(fill="x", pady=(6, 0))
        self._sequence_canvas = tk.Canvas(self.frame, height=120)
        seq_scroll = ttk.Scrollbar(self.frame, orient="horizontal", command=self._sequence_canvas.xview)
        self._sequence_canvas.configure(xscrollcommand=seq_scroll.set)
        self._sequence_canvas.pack(fill="x", expand=True)
        seq_scroll.pack(fill="x")

        # Populate only after the panel is shown and has a real width/height.

    def show(self, before_widget: tk.Widget | None = None) -> None:
        if not self._visible:
            pack_args = {"side": "bottom", "fill": "x", "padx": (0, 0), "pady": (6, 0)}
            if before_widget is not None:
                pack_args["before"] = before_widget
            self.frame.pack(**pack_args)
            self._visible = True
        self.refresh()

    def hide(self) -> None:
        if self._visible:
            self.frame.pack_forget()
            self._visible = False

    def toggle(self, before_widget: tk.Widget | None = None) -> None:
        if self._visible:
            self.hide()
        else:
            self.show(before_widget=before_widget)

    def refresh(self) -> None:
        self._populate_source()
        self._populate_sequence()

    def _load_photo(self, source: Path | SlideItem, max_size: tuple[int, int]) -> ImageTk.PhotoImage | None:
        path = source.source if isinstance(source, SlideItem) else source
        thumbnail_cache = getattr(self.controller, "thumbnail_cache", None)
        if thumbnail_cache is not None:
            cached = getattr(thumbnail_cache, "_cache", {}).get(str(path))
            if cached is not None:
                return cached
            placeholder = thumbnail_cache.get_photo(path, max_size=max_size)
            return placeholder
        if hasattr(self.controller, "cache") and self.controller.cache is not None:
            try:
                slide = source if isinstance(source, SlideItem) else SlideItem(path)
                if hasattr(self.controller.cache, "get_thumbnail"):
                    img = self.controller.cache.get_thumbnail(slide, max_size=max_size)
                    return ImageTk.PhotoImage(img)
            except Exception:
                pass
        try:
            img = Image.open(path)
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _redraw_canvas(self, canvas: tk.Canvas | None) -> None:
        if canvas is None:
            return
        # Avoid nested Tk event processing here: forcing a full canvas.update() from
        # inside a refresh can re-enter the GUI loop, delay async thumbnail callbacks,
        # and freeze the UI after a click on a thumbnail.
        try:
            canvas.update_idletasks()
        except tk.TclError:
            pass

    def _current_source_key(self) -> str | None:
        if self.controller is None:
            return None
        deck = getattr(self.controller, "deck", None)
        if deck is None or not hasattr(deck, "get_current"):
            return None
        current_slide = deck.get_current()
        if current_slide is None:
            return None
        try:
            return str(current_slide.source.resolve())
        except Exception:
            return str(current_slide.source)

    def _scroll_source_selection_into_view(self) -> None:
        if self._source_canvas is None:
            return
        try:
            self._source_canvas.update_idletasks()
        except tk.TclError:
            pass
        selected_key = self._current_source_key()
        if selected_key is None:
            return
        item_id = self._source_widget_ids.get(selected_key)
        if item_id is None:
            return
        try:
            bbox = self._source_canvas.bbox(item_id)
        except tk.TclError:
            return
        if not bbox:
            return
        left, _, right, _ = bbox
        canvas_width = max(1, self._source_canvas.winfo_width())
        total_width = self._source_canvas.bbox("all")
        if not total_width:
            return
        scroll_width = max(1, total_width[2] - total_width[0])
        view_left = self._source_canvas.canvasx(0)
        view_right = self._source_canvas.canvasx(canvas_width)
        if left < view_left:
            target = max(0.0, (left - 12) / scroll_width)
            self._source_canvas.xview_moveto(target)
        elif right > view_right:
            target = min(1.0, (right - canvas_width + 12) / scroll_width)
            self._source_canvas.xview_moveto(target)

    def _update_source_selection_state(self) -> None:
        selected_key = self._current_source_key()
        for path_key, label in self._source_widgets.items():
            is_selected = path_key == selected_key
            label.configure(
                bd=2 if is_selected else 0,
                relief="solid" if is_selected else "flat",
                highlightthickness=4 if is_selected else 0,
                highlightbackground="#fef3c7" if is_selected else "white",
                highlightcolor="#fef3c7" if is_selected else "white",
            )
        if self._source_canvas is not None and selected_key != self._last_source_selection_key:
            self._source_canvas.after_idle(self._scroll_source_selection_into_view)
        self._last_source_selection_key = selected_key

    def _select_source_slide(self, slide: SlideItem) -> None:
        if self.controller is None:
            return
        slides = self.controller.get_source_slides() if hasattr(self.controller, "get_source_slides") else []
        target_key = str(slide.source.resolve()) if slide.source.exists() else str(slide.source)
        for idx, source_slide in enumerate(slides):
            source_key = str(source_slide.source.resolve()) if source_slide.source.exists() else str(source_slide.source)
            if source_key == target_key:
                if hasattr(self.controller, "jump_to"):
                    self.controller.jump_to(idx)
                elif hasattr(self.controller, "deck") and hasattr(self.controller.deck, "jump_to"):
                    self.controller.deck.jump_to(idx)
                break
        self._update_source_selection_state()
        if self._source_canvas is not None:
            self._scroll_source_selection_into_view()

    def _populate_source(self) -> None:
        if self._source_canvas is None or self.controller is None:
            return
        old_scroll = self._source_canvas.xview()[0]
        previous_key = self._last_source_selection_key or self._current_source_key()
        slides = self.controller.get_source_slides() if hasattr(self.controller, "get_source_slides") else []
        slides_sorted = sorted(slides, key=lambda s: s.source.name.lower())
        self._source_canvas.delete("all")
        self._source_widgets.clear()
        self._source_widget_ids.clear()
        self._source_photos.clear()
        x = 4
        padding = 6
        h = 80
        for slide in slides_sorted:
            photo = self._load_photo(slide, (120, h))
            lbl = tk.Label(self._source_canvas, image=photo, bg='white', bd=0, highlightthickness=0, relief='flat', padx=2, pady=2)
            if photo is not None:
                self._source_photos.append(photo)
            window_id = self._source_canvas.create_window(x, 4, anchor='nw', window=lbl)
            try:
                path_key = str(slide.source.resolve())
            except Exception:
                path_key = str(slide.source)
            self._source_widgets[path_key] = lbl
            self._source_widget_ids[path_key] = window_id
            if hasattr(self.controller, 'thumbnail_cache'):
                def make_on_ready(widget):
                    def _on_ready(p, ph):
                        try:
                            widget.configure(image=ph)
                            widget.image = ph
                        except Exception:
                            pass
                    return _on_ready
                self.controller.thumbnail_cache.get_photo(
                    slide.source,
                    max_size=(120, h),
                    on_ready=make_on_ready(lbl),
                )
            def _on_source_click(event, s=slide):
                self._pending_drag_source = s
                self._select_source_slide(s)
            lbl.bind("<ButtonPress-1>", _on_source_click)
            lbl.bind("<B1-Motion>", self._on_drag_motion)
            lbl.bind("<ButtonRelease-1>", self._end_drag)
            x += 126 + padding
        self._source_canvas.config(scrollregion=(0, 0, x, h))
        self._source_canvas.update_idletasks()
        selected_key = self._current_source_key()
        if old_scroll > 0 and selected_key == previous_key:
            self._source_canvas.xview_moveto(old_scroll)
        self._update_source_selection_state()
        if old_scroll > 0 and selected_key == previous_key:
            self._source_canvas.xview_moveto(old_scroll)
        else:
            self._scroll_source_selection_into_view()
        self._redraw_canvas(self._source_canvas)
        self._last_source_selection_key = selected_key

    def _move_sequence_item(self, index: int, offset: int) -> None:
        if self.controller is None:
            return
        if hasattr(self.controller, "move_sequence_item"):
            self.controller.move_sequence_item(index, index + offset)
            self.refresh()

    def _remove_sequence_item(self, index: int) -> None:
        if self.controller is None:
            return
        if hasattr(self.controller, "remove_sequence_item"):
            self.controller.remove_sequence_item(index)
            self.refresh()

    def _populate_sequence(self) -> None:
        if self._sequence_canvas is None or self.controller is None:
            return
        seq = getattr(self.controller, "current_sequence", None)
        self._sequence_canvas.delete("all")
        self._sequence_photos.clear()
        if seq is None:
            return
        x = 4
        slot_w = 140
        for idx, path in enumerate(seq.items):
            try:
                slide = SlideItem(path)
                photo = self._load_photo(slide, (120, 80))
            except Exception:
                photo = None
            frame = ttk.Frame(self._sequence_canvas)
            lbl = tk.Label(frame, image=photo, bg='white', bd=0, highlightthickness=0)
            if photo is not None:
                self._sequence_photos.append(photo)
            lbl.pack()
            if hasattr(self.controller, 'thumbnail_cache'):
                def make_on_ready(widget):
                    def _on_ready(p, ph):
                        try:
                            widget.configure(image=ph)
                            widget.image = ph
                        except Exception:
                            pass
                    return _on_ready
                self.controller.thumbnail_cache.get_photo(
                    path,
                    max_size=(120, 80),
                    on_ready=make_on_ready(lbl),
                )
            self._sequence_canvas.create_window(x, 4, anchor='nw', window=frame)
            frame.bind("<ButtonPress-1>", lambda e, i=idx: self._start_drag_sequence(e, i))
            frame.bind("<B1-Motion>", self._on_drag_motion)
            frame.bind("<ButtonRelease-1>", self._end_drag)
            lbl.bind("<ButtonPress-1>", lambda e, i=idx: self._start_drag_sequence(e, i))
            lbl.bind("<B1-Motion>", self._on_drag_motion)
            lbl.bind("<ButtonRelease-1>", self._end_drag)
            x += slot_w
        self._sequence_canvas.config(scrollregion=(0, 0, x, 120))
        self._sequence_canvas.xview_moveto(0)
        self._redraw_canvas(self._sequence_canvas)

    def _new_sequence(self) -> None:
        name = simpledialog.askstring("New Sequence", "Sequence name:", parent=self.parent)
        if not name:
            return
        seq = Sequence(name=name, items=[])
        self.controller.current_sequence = seq
        self.refresh()

    def _save_sequence(self) -> None:
        if not hasattr(self.controller, "current_sequence") or self.controller.current_sequence is None:
            messagebox.showinfo("Save sequence", "No sequence to save.", parent=self.parent)
            return
        name = simpledialog.askstring("Save Sequence", "Sequence name:", initialvalue=self.controller.current_sequence.name, parent=self.parent)
        if not name:
            return
        self.controller.current_sequence.name = name
        if hasattr(self.controller, "sequence_store"):
            path = self.controller.sequence_store.save(self.controller.current_sequence)
            messagebox.showinfo("Saved", f"Sequence saved to: {path}", parent=self.parent)

    def _clear_sequence(self) -> None:
        if hasattr(self.controller, "current_sequence") and self.controller.current_sequence is not None:
            self.controller.current_sequence.items.clear()
            self.refresh()

    def _parse_ffmpeg_progress(self, line: str, total_frames: int) -> float | None:
        if total_frames <= 0:
            return None
        match = re.search(r"frame\s*=\s*(\d+)", line, flags=re.IGNORECASE)
        if match is None:
            return None
        try:
            frame_count = int(match.group(1))
        except ValueError:
            return None
        progress = (frame_count / total_frames) * 100.0
        return max(0.0, min(100.0, progress))

    def _play_exported_video(self, output_path: Path | str) -> None:
        path = Path(output_path).expanduser().resolve()
        try:
            subprocess.Popen(["vlc", str(path)])
        except FileNotFoundError:
            messagebox.showerror("Play video", "VLC is not installed or not available on PATH.", parent=self.parent)

    def _show_ffmpeg_status_dialog(self, total_frames: int) -> tk.Toplevel:
        dialog = tk.Toplevel(self.parent)
        dialog.title("Exporting MP4")
        dialog.transient(self.parent)
        dialog.grab_set()
        dialog.minsize(450, 250)

        status_var = tk.StringVar(value="Preparing export...")
        progress_var = tk.DoubleVar(value=0.0)

        header_row = ttk.Frame(dialog)
        header_row.pack(fill="x", padx=12, pady=(12, 6))
        ttk.Label(header_row, text="Exporting sequence to MP4", font=("Segoe UI", 10, "bold")).pack(side="left")

        button_row = ttk.Frame(dialog)
        button_row.pack(fill="x", padx=12, pady=(0, 8))
        play_btn = ttk.Button(button_row, text="Play", state="disabled")
        play_btn.pack(side="right")
        cancel_btn = ttk.Button(button_row, text="Cancel")
        cancel_btn.pack(side="right", padx=(0, 8))

        ttk.Label(dialog, textvariable=status_var).pack(anchor="w", padx=12)

        progress = ttk.Progressbar(dialog, orient="horizontal", mode="determinate", maximum=100, value=0)
        progress.pack(fill="x", padx=12, pady=(8, 12))

        text = tk.Text(dialog, wrap="word", height=12, state="disabled", bg="#f8f8f8")
        text_scroll = ttk.Scrollbar(dialog, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=text_scroll.set)
        text.pack(fill="both", expand=True, padx=(12, 0), pady=(0, 12), side="left")
        text_scroll.pack(fill="y", side="right", padx=(0, 12), pady=(0, 12))

        dialog.status_var = status_var
        dialog.progress_var = progress_var
        dialog.progress_bar = progress
        dialog.text_widget = text
        dialog.cancel_button = cancel_btn
        dialog.play_button = play_btn
        dialog._cancel_requested = False
        dialog._process = None
        dialog._cleanup_temp_dir = None
        return dialog

    def _append_ffmpeg_output(self, dialog: tk.Toplevel, line: str) -> None:
        if not dialog.winfo_exists():
            return
        text_widget = dialog.text_widget
        text_widget.configure(state="normal")
        text_widget.insert("end", f"{line}\n")
        text_widget.see("end")
        text_widget.configure(state="disabled")

    def _combine_export_progress(self, ffmpeg_progress_percent: float, ffmpeg_phase_start_percent: float) -> float:
        return max(0.0, min(100.0, ffmpeg_phase_start_percent + (ffmpeg_progress_percent / 100.0) * (100.0 - ffmpeg_phase_start_percent)))

    def _set_export_progress(self, dialog: tk.Toplevel, percent: float, status: str | None = None) -> None:
        if not dialog.winfo_exists():
            return
        dialog.progress_bar["maximum"] = 100
        dialog.progress_bar["value"] = max(0.0, min(100.0, percent))
        if status is not None:
            dialog.status_var.set(status)

    def _update_ffmpeg_progress(self, dialog: tk.Toplevel, progress_value: float) -> None:
        if not dialog.winfo_exists():
            return
        combined = self._combine_export_progress(progress_value, 80.0)
        dialog.progress_bar["maximum"] = 100
        dialog.progress_bar["value"] = min(99.9, max(0, combined))
        dialog.status_var.set(f"{combined:.1f}% complete")

    def _cancel_ffmpeg_process(self, dialog: tk.Toplevel, process: subprocess.Popen[str] | None) -> None:
        if dialog._cancel_requested:
            return
        dialog._cancel_requested = True
        dialog.status_var.set("Cancelling export...")
        dialog.cancel_button.configure(state="disabled")
        if process is None or process.poll() is not None:
            dialog.destroy()
            return
        try:
            process.terminate()
        except Exception:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except Exception:
                pass
            process.wait(timeout=5)

    def _handle_ffmpeg_finish(
        self,
        dialog: tk.Toplevel,
        process: subprocess.Popen[str],
        output_path: Path,
        temp_dir: Path,
    ) -> None:
        if not dialog.winfo_exists():
            return

        if dialog._cancel_requested:
            dialog.status_var.set("Export cancelled.")
            dialog.cancel_button.configure(text="Close")
            dialog.cancel_button.configure(command=dialog.destroy)
            dialog.cancel_button.configure(state="normal")
            dialog.play_button.configure(state="disabled")
            shutil.rmtree(temp_dir, ignore_errors=True)
            dialog.after(250, dialog.destroy)
            return

        return_code = process.returncode
        if return_code == 0:
            self._set_export_progress(dialog, 100.0, "Export complete")
            dialog.cancel_button.configure(text="Close")
            dialog.cancel_button.configure(command=dialog.destroy)
            dialog.cancel_button.configure(state="normal")
            dialog.play_button.configure(state="normal", command=lambda: self._play_exported_video(output_path))
            messagebox.showinfo("Export complete", f"Video saved to: {output_path}", parent=self.parent)
        else:
            self._set_export_progress(dialog, 0.0, f"Export failed (exit code {return_code})")
            dialog.cancel_button.configure(text="Close")
            dialog.cancel_button.configure(command=dialog.destroy)
            dialog.cancel_button.configure(state="normal")
            dialog.play_button.configure(state="disabled")
            messagebox.showerror("Export video", f"ffmpeg failed while exporting the video to {output_path}.", parent=self.parent)
        shutil.rmtree(temp_dir, ignore_errors=True)

    def _read_ffmpeg_output(self, process: subprocess.Popen[str], dialog: tk.Toplevel, total_frames: int, output_path: Path, temp_dir: Path) -> None:
        try:
            if process.stdout is not None:
                for raw_line in iter(process.stdout.readline, ""):
                    line = raw_line.rstrip()
                    if not line:
                        continue
                    dialog.after(0, self._append_ffmpeg_output, dialog, line)
                    progress_value = self._parse_ffmpeg_progress(line, total_frames)
                    if progress_value is not None:
                        dialog.after(0, self._update_ffmpeg_progress, dialog, progress_value)
            process.wait()
            dialog.after(0, self._handle_ffmpeg_finish, dialog, process, output_path, temp_dir)
        except Exception:
            dialog.after(0, self._handle_ffmpeg_finish, dialog, process, output_path, temp_dir)

    def _export_sequence_video(self) -> None:
        if self.controller is None:
            return
        seq = getattr(self.controller, "current_sequence", None)
        if seq is None or not seq.items:
            messagebox.showinfo("Export video", "No sequence items to export.", parent=self.parent)
            return

        output_path = filedialog.asksaveasfilename(
            parent=self.parent,
            title="Save video as",
            defaultextension=".mp4",
            filetypes=[("MP4 Video", "*.mp4"), ("All Files", "*.*")],
            initialfile=f"{seq.name or 'sequence'}.mp4",
        )
        if not output_path:
            return

        output_path = Path(output_path).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        dialog = self._show_ffmpeg_status_dialog(total_frames=max(1, len(seq.items)))
        self._set_export_progress(dialog, 0.0, "Preparing MP4 export...")
        self._append_ffmpeg_output(dialog, "Preparing MP4 export...")
        self._append_ffmpeg_output(dialog, f"Processing {len(seq.items)} sequence items.")
        self._append_ffmpeg_output(dialog, "Generating source frames...")
        dialog.update_idletasks()

        temp_dir = Path(tempfile.mkdtemp(prefix="crowdcurate-seq-"))
        frame_list_path = temp_dir / "frames.txt"
        frame_paths: list[Path] = []
        try:
            source_total = max(1, len(seq.items))
            for index, item_path in enumerate(seq.items, start=1):
                source = Path(item_path)
                if not source.exists():
                    continue
                try:
                    with Image.open(source) as img:
                        rgb_img = img.convert("RGB")
                        frame_size = (1280, 720)
                        aspect_ratio = rgb_img.width / rgb_img.height
                        target_ratio = frame_size[0] / frame_size[1]

                        if aspect_ratio > target_ratio:
                            new_width = frame_size[0]
                            new_height = max(1, int(frame_size[0] / aspect_ratio))
                            offset_y = (frame_size[1] - new_height) // 2
                            resized = rgb_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                            canvas = Image.new("RGB", frame_size, (0, 0, 0))
                            canvas.paste(resized, (0, offset_y))
                        else:
                            new_height = frame_size[1]
                            new_width = max(1, int(frame_size[1] * aspect_ratio))
                            offset_x = (frame_size[0] - new_width) // 2
                            resized = rgb_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                            canvas = Image.new("RGB", frame_size, (0, 0, 0))
                            canvas.paste(resized, (offset_x, 0))

                        frame_path = temp_dir / f"frame_{index:04d}.png"
                        canvas.save(frame_path, format="PNG")
                        frame_paths.append(frame_path)
                    source_progress = (index / source_total) * 30.0
                    self._set_export_progress(dialog, source_progress, "Generating source frames...")
                    dialog.update_idletasks()
                except Exception:
                    continue

            if not frame_paths:
                dialog.destroy()
                messagebox.showerror("Export video", "No valid image frames were found to export.", parent=self.parent)
                shutil.rmtree(temp_dir, ignore_errors=True)
                return

            self._append_ffmpeg_output(dialog, f"Built {len(frame_paths)} source frames; preparing fades and export list...")
            self._set_export_progress(dialog, 35.0, "Preparing ffmpeg export...")
            dialog.update_idletasks()

            fade_duration = 0.75
            fade_steps = 20
            step_duration = fade_duration / fade_steps
            fade_paths: list[Path] = []
            fade_total = max(1, len(frame_paths) * (fade_steps + 2))
            fade_processed = 0
            for frame_path in frame_paths:
                fade_paths.append(frame_path)
                with Image.open(frame_path) as img:
                    base = img.convert("RGBA")
                for step in range(1, fade_steps + 1):
                    alpha = step / fade_steps
                    overlay = Image.new("RGBA", base.size, (0, 0, 0, int(255 * alpha)))
                    combined = Image.alpha_composite(base, overlay)
                    fade_frame = temp_dir / f"fade_{frame_path.stem}_{step:02d}.png"
                    combined.convert("RGB").save(fade_frame, format="PNG")
                    fade_paths.append(fade_frame)
                    fade_processed += 1
                    progress = 35.0 + (fade_processed / fade_total) * 45.0
                    self._set_export_progress(dialog, progress, "Preparing fades...")
                    dialog.update_idletasks()
                black = Image.new("RGB", (1280, 720), (0, 0, 0))
                black_path = temp_dir / f"black_{frame_path.stem}.png"
                black.save(black_path, format="PNG")
                fade_paths.append(black_path)
                fade_processed += 1
                progress = 35.0 + (fade_processed / fade_total) * 45.0
                self._set_export_progress(dialog, progress, "Preparing fades...")
                dialog.update_idletasks()

            with frame_list_path.open("w", encoding="utf-8") as fh:
                for i, frame_path in enumerate(fade_paths):
                    fh.write(f"file '{frame_path.as_posix()}'\n")
                    if i == 0 or i % (fade_steps + 2) == 0:
                        fh.write("duration 2.0\n")
                    else:
                        fh.write(f"duration {step_duration:.3f}\n")
                if fade_paths:
                    fh.write(f"file '{fade_paths[-1].as_posix()}'\n")

            ffmpeg_cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(frame_list_path),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ]

            self._set_export_progress(dialog, 80.0, "Launching ffmpeg...")
            self._append_ffmpeg_output(dialog, "Encoding MP4 with ffmpeg...")
            self._append_ffmpeg_output(dialog, f"ffmpeg command: {' '.join(ffmpeg_cmd)}")
            dialog.cancel_button.configure(command=lambda: self._cancel_ffmpeg_process(dialog, dialog._process))
            dialog.play_button.configure(command=lambda: self._play_exported_video(output_path))
            try:
                process = subprocess.Popen(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except FileNotFoundError:
                dialog.destroy()
                messagebox.showerror("Export video", "ffmpeg is not installed or not available on PATH.", parent=self.parent)
                shutil.rmtree(temp_dir, ignore_errors=True)
                return

            dialog._process = process
            threading.Thread(target=self._read_ffmpeg_output, args=(process, dialog, max(1, len(fade_paths)), output_path, temp_dir), daemon=True).start()
            dialog.protocol("WM_DELETE_WINDOW", lambda: self._cancel_ffmpeg_process(dialog, dialog._process))
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            messagebox.showerror("Export video", f"ffmpeg failed while exporting the video to {output_path}.", parent=self.parent)

    # DnD handlers
    def _start_drag_source(self, event: tk.Event, slide: SlideItem) -> None:
        if self._dragging:
            return
        self._dragging = True
        self._drag_moved = False
        self._pending_drag_source = None
        self._drag_source_path = slide.source
        self._drag_from_index = None
        self._bind_drag_root_events()
        # try to get a cached photo (placeholder or real) from thumbnail_cache
        try:
            self._drag_photo = self._load_photo(slide, (120, 80))
        except Exception:
            self._drag_photo = None
        self._create_ghost(event)

    def _start_drag_sequence(self, event: tk.Event, index: int) -> None:
        if self._dragging:
            return
        self._dragging = True
        self._drag_moved = False
        self._pending_drag_source = None
        self._drag_from_index = index
        self._drag_source_path = None
        self._bind_drag_root_events()
        seq = getattr(self.controller, "current_sequence", None)
        if seq is None:
            return
        path = seq.items[index]
        try:
            self._drag_photo = self._load_photo(path, (120, 80))
        except Exception:
            self._drag_photo = None
        self._create_ghost(event)

    def _bind_drag_root_events(self) -> None:
        root = self.parent.winfo_toplevel()
        if root is None:
            return
        root.bind("<B1-Motion>", self._on_drag_motion, add="+")
        root.bind("<ButtonRelease-1>", self._end_drag, add="+")

    def _unbind_drag_root_events(self) -> None:
        root = self.parent.winfo_toplevel()
        if root is None:
            return
        try:
            root.unbind("<B1-Motion>")
        except Exception:
            pass
        try:
            root.unbind("<ButtonRelease-1>")
        except Exception:
            pass

    def _create_ghost(self, event: tk.Event) -> None:
        if self._drag_ghost is not None:
            try:
                self._drag_ghost.destroy()
            except Exception:
                pass
        self._drag_ghost = tk.Toplevel(self.parent.winfo_toplevel())
        self._drag_ghost.overrideredirect(True)
        if self._drag_photo is not None:
            ttk.Label(self._drag_ghost, image=self._drag_photo).pack()
        else:
            ttk.Label(self._drag_ghost, text="img").pack()
        try:
            self._drag_ghost.geometry(f"+{event.x_root+8}+{event.y_root+8}")
        except Exception:
            pass

    def _on_drag_motion(self, event: tk.Event) -> None:
        if not self._dragging and self._pending_drag_source is not None:
            self._start_drag_source(event, self._pending_drag_source)
        if not self._dragging:
            return
        if not self._drag_moved:
            self._drag_moved = True
        if self._drag_ghost is None:
            return
        try:
            self._drag_ghost.geometry(f"+{event.x_root+8}+{event.y_root+8}")
        except Exception:
            pass

    def _end_drag(self, event: tk.Event) -> None:
        if not self._dragging:
            return
        if not self._drag_moved:
            if self._drag_from_index is None and self._drag_source_path is not None:
                self._select_source_slide(SlideItem(self._drag_source_path))
            if self._drag_ghost is not None:
                try:
                    self._drag_ghost.destroy()
                except Exception:
                    pass
            self._drag_ghost = None
            self._drag_photo = None
            self._dragging = False
            self._drag_moved = False
            self._pending_drag_source = None
            self._drag_source_path = None
            self._drag_from_index = None
            self._unbind_drag_root_events()
            return
        # determine drop index based on x over sequence canvas
        drop_index = 0
        try:
            canvas = self._sequence_canvas
            if canvas is not None:
                rel_x = event.x_root - canvas.winfo_rootx()
                slot_w = 140
                drop_index = max(0, int(rel_x // slot_w))
        except Exception:
            drop_index = 0
        # if came from source
        if self._drag_from_index is None and self._drag_source_path is not None:
            if not hasattr(self.controller, "current_sequence") or self.controller.current_sequence is None:
                self.controller.current_sequence = Sequence(name="Untitled", items=[])
            self.controller.current_sequence.items.insert(drop_index, self._drag_source_path)
        elif self._drag_from_index is not None:
            # reorder within sequence
            seq = getattr(self.controller, "current_sequence", None)
            if seq is not None and 0 <= self._drag_from_index < len(seq.items):
                item = seq.items.pop(self._drag_from_index)
                idx = max(0, min(drop_index, len(seq.items)))
                seq.items.insert(idx, item)
        # cleanup
        if self._drag_ghost is not None:
            try:
                self._drag_ghost.destroy()
            except Exception:
                pass
        self._drag_ghost = None
        self._drag_photo = None
        self._dragging = False
        self._drag_moved = False
        self._pending_drag_source = None
        self._drag_source_path = None
        self._drag_from_index = None
        self._unbind_drag_root_events()
        # refresh panels
        self.refresh()
