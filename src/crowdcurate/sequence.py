from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
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

    def _populate_source(self) -> None:
        if self._source_canvas is None or self.controller is None:
            return
        old_scroll = self._source_canvas.xview()[0]
        slides = self.controller.get_source_slides() if hasattr(self.controller, "get_source_slides") else []
        slides_sorted = sorted(slides, key=lambda s: s.source.name.lower())
        self._source_canvas.delete("all")
        self._source_widgets.clear()
        self._source_photos.clear()
        x = 4
        padding = 6
        h = 80
        for slide in slides_sorted:
            photo = self._load_photo(slide, (120, h))
            lbl = tk.Label(self._source_canvas, image=photo, bg='white', bd=0, highlightthickness=0, relief='flat', padx=2, pady=2)
            if photo is not None:
                self._source_photos.append(photo)
            self._source_canvas.create_window(x, 4, anchor='nw', window=lbl)
            try:
                self._source_widgets[str(slide.source.resolve())] = lbl
            except Exception:
                self._source_widgets[str(slide.source)] = lbl
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
        self._update_source_selection_state()
        self._source_canvas.config(scrollregion=(0, 0, x, h))
        if old_scroll > 0:
            self._source_canvas.xview_moveto(old_scroll)
        self._redraw_canvas(self._source_canvas)

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
            ctrl = ttk.Frame(frame)
            ttk.Button(ctrl, text='◀', width=2, command=lambda i=idx: self._move_sequence_item(i, -1)).pack(side='left')
            ttk.Button(ctrl, text='▶', width=2, command=lambda i=idx: self._move_sequence_item(i, 1)).pack(side='left')
            ttk.Button(ctrl, text='✖', width=2, command=lambda i=idx: self._remove_sequence_item(i)).pack(side='left')
            ctrl.pack()
            self._sequence_canvas.create_window(x, 4, anchor='nw', window=frame)
            frame.bind("<ButtonPress-1>", lambda e, i=idx: self._start_drag_sequence(e, i))
            frame.bind("<B1-Motion>", self._on_drag_motion)
            frame.bind("<ButtonRelease-1>", self._end_drag)
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

        temp_dir = Path(tempfile.mkdtemp(prefix="crowdcurate-seq-"))
        frame_list_path = temp_dir / "frames.txt"
        frame_paths: list[Path] = []
        try:
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
                except Exception:
                    continue

            if not frame_paths:
                messagebox.showerror("Export video", "No valid image frames were found to export.", parent=self.parent)
                return

            fade_duration = 0.75
            fade_steps = 20
            step_duration = fade_duration / fade_steps
            fade_paths: list[Path] = []
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
                black = Image.new("RGB", (1280, 720), (0, 0, 0))
                black_path = temp_dir / f"black_{frame_path.stem}.png"
                black.save(black_path, format="PNG")
                fade_paths.append(black_path)

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
            subprocess.run(ffmpeg_cmd, check=True)
            messagebox.showinfo("Export complete", f"Video saved to: {output_path}", parent=self.parent)
        except FileNotFoundError:
            messagebox.showerror("Export video", "ffmpeg is not installed or not available on PATH.", parent=self.parent)
        except subprocess.CalledProcessError:
            messagebox.showerror("Export video", f"ffmpeg failed while exporting the video to {output_path}.", parent=self.parent)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

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
