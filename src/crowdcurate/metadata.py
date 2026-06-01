from __future__ import annotations

import hashlib
import shutil
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Any

import piexif  # type: ignore[import]
from PIL import Image

EXIF_TYPE_ASCII = 2
EXIF_TYPE_SHORT = 3
EXIF_TYPE_LONG = 4
EXIF_TYPE_RATIONAL = 5
EXIF_TYPE_SSHORT = 8
EXIF_TYPE_SLONG = 9
EXIF_TYPE_SRATIONAL = 10

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
            pack_args: dict[str, Any] = {
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
        except (OSError, ValueError) as exc:
            lines.append(f"Error reading image: {exc}")

        return "\n".join(lines)

    @staticmethod
    def _compute_sha256(path: Path) -> str:
        sha256_hash = hashlib.sha256()
        with open(path, "rb") as file_obj:
            for byte_block in iter(lambda: file_obj.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()


class ExifEditorWindow:
    """Dialog window for viewing and editing EXIF and IPTC metadata."""

    def __init__(self, parent: Any, file_path: Path) -> None:
        self.parent = parent
        self.file_path = file_path
        self.exif_data: dict[str, Any] = {}
        self.tag_mapping: dict[str, tuple[str, int]] = {}
        self.tag_types: dict[tuple[str, int], int] = {}
        self.exif_text: tk.Text
        self._load_metadata()
        self._create_dialog()

    def _load_metadata(self) -> None:
        """Load EXIF and basic metadata from the image file."""
        try:
            exif_dict = piexif.load(str(self.file_path))
            self.exif_data = exif_dict
            # Store tag type information for later use
            for ifd_name in ("0th", "Exif", "GPS", "1st"):
                ifd = self.exif_data.get(ifd_name)
                if ifd:
                    for tag_id in ifd.keys():
                        try:
                            tag_type = piexif.TAGS[ifd_name][tag_id]["type"]
                            self.tag_types[(ifd_name, tag_id)] = tag_type
                        except (KeyError, TypeError):
                            pass
        except (OSError, ValueError) as exc:
            messagebox.showerror(
                "Error", f"Could not read EXIF data: {exc}", parent=self.parent
            )

    def _create_dialog(self) -> None:
        """Create the EXIF editor dialog."""
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("EXIF/IPTC Editor")
        self.dialog.geometry("600x500")
        self.dialog.transient(self.parent)
        self.dialog.grab_set()

        # Main frame
        main_frame = ttk.Frame(self.dialog)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # File info
        file_label = ttk.Label(
            main_frame,
            text=f"File: {self.file_path.name}",
            font=("Segoe UI", 10, "bold"),
        )
        file_label.pack(fill="x", pady=(0, 10))

        # Notebook for tabs
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill="both", expand=True, pady=(0, 10))

        # EXIF tab
        exif_frame = ttk.Frame(notebook)
        notebook.add(exif_frame, text="EXIF")
        self._create_exif_tab(exif_frame)

        # IPTC tab (placeholder)
        iptc_frame = ttk.Frame(notebook)
        notebook.add(iptc_frame, text="IPTC")
        ttk.Label(iptc_frame, text="IPTC editing not yet implemented").pack(
            padx=10, pady=10
        )

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x")
        ttk.Button(button_frame, text="Close", command=self.dialog.destroy).pack(
            side="right", padx=(5, 0)
        )
        ttk.Button(
            button_frame, text="Save Changes", command=self._save_exif
        ).pack(side="right", padx=(5, 0))

    def _create_exif_tab(self, parent: tk.Widget) -> None:
        """Create the EXIF data display and edit area."""
        # Create a text widget to show EXIF tags
        text_frame = ttk.Frame(parent)
        text_frame.pack(fill="both", expand=True, padx=10, pady=10)

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")

        self.exif_text = tk.Text(
            text_frame,
            yscrollcommand=scrollbar.set,
            wrap=tk.WORD,
            height=15,
            width=70,
        )
        self.exif_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.exif_text.yview)

        # Display EXIF data
        self._display_exif()

        # Info label
        info_label = ttk.Label(
            parent,
            text="(Edit values above and click 'Save Changes' to write back to file)",
            font=("Segoe UI", 9, "italic"),
        )
        info_label.pack(fill="x", padx=10, pady=(0, 10))

    def _display_exif(self) -> None:
        """Populate the EXIF text widget with editable EXIF data."""
        self.exif_text.config(state=tk.NORMAL)
        self.exif_text.delete("1.0", tk.END)
        self.tag_mapping.clear()

        if not self.exif_data:
            self.exif_text.insert(tk.END, "No EXIF data found.")
            return

        # Display EXIF tags in an editable format
        output = []

        for ifd_name in ("0th", "Exif", "GPS", "1st"):
            ifd = self.exif_data.get(ifd_name)
            if ifd:
                output.append(f"[{ifd_name}]")
                for tag_id, value in ifd.items():
                    try:
                        tag_name = piexif.TAGS[ifd_name][tag_id]["name"]
                        map_key = f"{ifd_name}:{tag_name}"
                        self.tag_mapping[map_key] = (ifd_name, tag_id)
                        if isinstance(value, bytes):
                            value_str = value.decode("utf-8", errors="ignore")
                        else:
                            value_str = str(value)
                        output.append(f"{tag_name}={value_str}")
                    except (KeyError, UnicodeDecodeError) as exc:
                        output.append(f"Tag {tag_id}=[Error reading: {exc}]")
                output.append("")

        if output:
            self.exif_text.insert(tk.END, "\n".join(output))
        else:
            self.exif_text.insert(tk.END, "No EXIF tags found.")

    def _save_exif(self) -> None:
        """Save EXIF changes back to the file."""
        try:
            text_content = self.exif_text.get("1.0", tk.END)
            edited_exif = self._parse_exif_text(text_content)
            if not edited_exif:
                messagebox.showwarning(
                    "No changes",
                    "No valid EXIF data to save.",
                    parent=self.dialog,
                )
                return
            for ifd_name in ("0th", "Exif", "GPS", "1st"):
                if ifd_name not in edited_exif:
                    edited_exif[ifd_name] = {}
            backup_path = self.file_path.with_suffix(self.file_path.suffix + ".bak")
            shutil.copy2(self.file_path, backup_path)
            exif_bytes = piexif.dump(edited_exif)
            piexif.insert(exif_bytes, str(self.file_path))
            messagebox.showinfo(
                "Success",
                "EXIF data saved successfully!\n\n"
                f"Backup saved to:\n{backup_path.name}",
                parent=self.dialog,
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror(
                "Save Error",
                f"Failed to save EXIF data:\n{exc}",
                parent=self.dialog,
            )

    def _parse_exif_text(self, text: str) -> dict[str, Any]:
        """Parse the edited EXIF text format back into piexif format."""
        result: dict[str, Any] = {}
        current_ifd = ""

        for line in text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_ifd = line[1:-1]
                if current_ifd not in result:
                    result[current_ifd] = {}
                continue
            if "=" in line and current_ifd:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                map_key = f"{current_ifd}:{key}"
                if map_key not in self.tag_mapping:
                    continue
                ifd_name, tag_id = self.tag_mapping[map_key]
                if ifd_name not in result:
                    result[ifd_name] = {}
                converted_value = self._convert_exif_value(ifd_name, tag_id, value)
                result[ifd_name][tag_id] = converted_value
        return result

    def _convert_exif_value(
        self, ifd_name: str, tag_id: int, value_str: str
    ) -> Any:
        """Convert a string value to the appropriate EXIF data type."""
        tag_type = self.tag_types.get((ifd_name, tag_id), EXIF_TYPE_ASCII)
        if tag_type == EXIF_TYPE_ASCII:
            return self._as_bytes(value_str)
        if tag_type in (EXIF_TYPE_SHORT, EXIF_TYPE_SSHORT):
            return int(value_str)
        if tag_type in (EXIF_TYPE_LONG, EXIF_TYPE_SLONG):
            return int(value_str)
        if tag_type in (EXIF_TYPE_RATIONAL, EXIF_TYPE_SRATIONAL):
            return self._as_rational(value_str)
        return self._int_or_bytes(value_str)

    def _as_bytes(self, value_str: str) -> bytes | str:
        if isinstance(value_str, str):
            return value_str.encode("utf-8")
        return value_str

    def _as_rational(self, value_str: str) -> tuple[int, int]:
        if "/" in value_str:
            left, right = value_str.split("/", 1)
            return (int(left.strip()), int(right.strip()))
        try:
            fval = float(value_str)
            return (int(fval * 1000), 1000)
        except ValueError:
            return (1, 1)

    def _int_or_bytes(self, value_str: str) -> Any:
        try:
            return int(value_str)
        except ValueError:
            return self._as_bytes(value_str)
