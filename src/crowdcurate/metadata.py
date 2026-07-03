from __future__ import annotations

import hashlib
import logging
import shutil
import tkinter as tk
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from typing import TYPE_CHECKING, Any, cast

import piexif  # type: ignore[import-untyped]
from PIL import Image

# Configure logging for errors
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Pylint: some functions here parse binary formats and are necessarily complex.
# Disable specific style checks that would require large refactors.
# pylint: disable=too-many-instance-attributes,too-many-branches,too-many-nested-blocks,no-else-break

EXIF_TYPE_ASCII = 2
EXIF_TYPE_SHORT = 3
EXIF_TYPE_LONG = 4
EXIF_TYPE_RATIONAL = 5
EXIF_TYPE_SSHORT = 8
EXIF_TYPE_SLONG = 9
EXIF_TYPE_SRATIONAL = 10

if TYPE_CHECKING:
    from .model import SlideItem


def _indent_xml(elem: ET.Element, level: int = 0) -> str:
    """Format XML element with proper indentation."""
    indent_str = "  " * level
    result = f"{indent_str}<{elem.tag}"

    if elem.attrib:
        for key, value in elem.attrib.items():
            result += f' {key}="{value}"'

    if len(elem) == 0 and not elem.text:
        result += " />\n"
    else:
        result += ">"
        if elem.text and elem.text.strip():
            result += elem.text
        else:
            result += "\n"

        for child in elem:
            result += _indent_xml(child, level + 1)

        if not elem.text or not elem.text.strip():
            result += indent_str

        result += f"</{elem.tag}>\n"

    return result


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
            f"Path: {slide.source}",
            "",
            f"SHA256: {self.current_hash or 'Unavailable'}",
            "",
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


class ExifEditorWindow:  # pylint: disable=too-many-instance-attributes
    """Dialog window for viewing and editing EXIF and IPTC metadata."""

    def __init__(self, parent: Any, file_path: Path) -> None:
        self.parent = parent
        self.file_path = file_path
        self.exif_data: dict[str, Any] = {}
        self.tag_mapping: dict[str, tuple[str, int]] = {}
        self.tag_types: dict[tuple[str, int], int] = {}
        self.exif_text: tk.Text
        self.xmp_text: tk.Text
        self.xmp_data: str = ""
        self.status_label: ttk.Label | None = None
        self._load_metadata()
        self._create_dialog()

    def _load_metadata(self) -> None:
        """Load EXIF, IPTC, and XMP metadata from the image file."""
        # Load EXIF data
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
            # Log error instead of showing modal dialog
            logger.warning("Could not read EXIF data from %s: %s", self.file_path, exc)

        # Load XMP data
        self._load_xmp()

    def _create_dialog(self) -> None:
        """Create the EXIF editor dialog."""
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("EXIF/IPTC/XMP Editor")
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

        # XMP tab
        xmp_frame = ttk.Frame(notebook)
        notebook.add(xmp_frame, text="XMP")
        self._create_xmp_tab(xmp_frame)

        # IPTC tab (placeholder)
        iptc_frame = ttk.Frame(notebook)
        notebook.add(iptc_frame, text="IPTC")
        ttk.Label(iptc_frame, text="IPTC editing not yet implemented").pack(
            padx=10, pady=10
        )

        # Status label (non-blocking message display)
        self.status_label = ttk.Label(
            main_frame,
            text="Ready",
            font=("Segoe UI", 9),
            foreground="gray",
        )
        self.status_label.pack(fill="x", pady=(0, 5))

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x")
        ttk.Button(button_frame, text="Close", command=self.dialog.destroy).pack(
            side="right", padx=(5, 0)
        )
        ttk.Button(button_frame, text="Save Changes", command=self._save_metadata).pack(
            side="right", padx=(5, 0)
        )

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

    def _create_xmp_tab(self, parent: tk.Widget) -> None:
        """Create the XMP data display and edit area."""
        # Create a text widget to show XMP tags
        text_frame = ttk.Frame(parent)
        text_frame.pack(fill="both", expand=True, padx=10, pady=10)

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")

        self.xmp_text = tk.Text(
            text_frame,
            yscrollcommand=scrollbar.set,
            wrap=tk.WORD,
            height=15,
            width=70,
        )
        self.xmp_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.xmp_text.yview)

        # Display XMP data
        self._display_xmp()

        # Info label
        info_label = ttk.Label(
            parent,
            text=(
                "(XMP is stored as XML. Edit values and click 'Save Changes' "
                "to write back to file)"
            ),
            font=("Segoe UI", 9, "italic"),
        )
        info_label.pack(fill="x", padx=10, pady=(0, 10))

    def _set_status(
        self, message: str, color: str = "black", timeout_ms: int = 0
    ) -> None:
        """Update status label with a message."""
        if not hasattr(self, "status_label") or self.status_label is None:
            return
        if not hasattr(self, "dialog"):
            return
        self.status_label.config(text=message, foreground=color)
        try:
            self.dialog.update_idletasks()
        except tk.TclError:
            # Dialog may have been destroyed
            pass

        # Auto-clear after timeout if specified
        if timeout_ms > 0 and hasattr(self, "dialog"):
            try:
                self.dialog.after(timeout_ms, lambda: self._set_status("Ready", "gray"))
            except tk.TclError:
                pass

    def _load_xmp(self) -> None:
        """Extract XMP data from the image file."""
        try:
            # Try to read XMP from JPEG using PIL
            if self.file_path.suffix.lower() in (".jpg", ".jpeg"):
                self.xmp_data = self._extract_xmp_from_jpeg()
            elif self.file_path.suffix.lower() in (".png", ".tif", ".tiff"):
                self.xmp_data = self._extract_xmp_from_png()
            else:
                # Try PIL's generic approach
                try:
                    with Image.open(self.file_path) as img:
                        xmp_data = img.info.get("XMP")
                        if isinstance(xmp_data, bytes):
                            self.xmp_data = xmp_data.decode("utf-8", errors="ignore")
                except (OSError, ValueError):
                    pass
        except Exception:  # pylint: disable=broad-except
            pass  # XMP is optional, don't fail if not available

    def _extract_xmp_from_jpeg(
        self,
    ) -> str:  # pylint: disable=too-many-branches,too-many-nested-blocks
        """Extract XMP data from JPEG APP1 marker."""
        try:
            with open(self.file_path, "rb") as f:
                data = f.read()

            # Look for JPEG APP1 marker (FFE1)
            i = 0
            while i < len(data) - 9:
                if data[i : i + 2] == b"\xff\xe1":  # APP1 marker
                    # Get length
                    length = int.from_bytes(data[i + 2 : i + 4], "big")
                    app1_data = data[i + 4 : i + 4 + length - 2]

                    # Check if it's XMP (contains adobe xap namespace)
                    # Supports both Adobe XMP namespace variants
                    if b"adobe.com/xap" in app1_data or b"adobe:ns:meta" in app1_data:
                        # Find XMP data start - look for XML declaration or root element
                        # XMP packet format: [header]\0[data][trailer]
                        xmp_start = app1_data.find(b"<?xpacket")
                        if xmp_start == -1:
                            xmp_start = app1_data.find(b"<?xml")
                        if xmp_start == -1:
                            xmp_start = app1_data.find(b"<x:xmpmeta")
                        if xmp_start == -1:
                            xmp_start = app1_data.find(b"<rdf:RDF")

                        if xmp_start >= 0:
                            # Find the end - look for xpacket end or XML closing tag
                            xmp_end = app1_data.find(b"<?xpacket end", xmp_start)
                            if xmp_end == -1:
                                xmp_end = app1_data.find(b"?>", xmp_start)
                            if xmp_end == -1:
                                # No explicit end found; search for common closing tags
                                rdf_end = app1_data.find(b"</rdf:RDF>", xmp_start)
                                xmpmeta_end = app1_data.find(b"</x:xmpmeta>", xmp_start)
                                if rdf_end >= 0 and xmpmeta_end >= 0:
                                    xmp_end = max(
                                        rdf_end + len(b"</rdf:RDF>"),
                                        xmpmeta_end + len(b"</x:xmpmeta>"),
                                    )
                                elif rdf_end >= 0:
                                    xmp_end = rdf_end + len(b"</rdf:RDF>")
                                elif xmpmeta_end >= 0:
                                    xmp_end = xmpmeta_end + len(b"</x:xmpmeta>")

                            if xmp_end > xmp_start:
                                xmp_data = app1_data[xmp_start:xmp_end]
                                return xmp_data.decode("utf-8", errors="ignore")
                    i += length + 2
                i += 1
        except (OSError, ValueError):
            pass

        return ""

    def _extract_xmp_from_png(self) -> str:
        """Extract XMP data from PNG iTXt chunk."""
        try:
            with Image.open(self.file_path) as img:
                # Check for raw XMP data in image info
                if "XMP" in img.info:
                    xmp_data = img.info["XMP"]
                    if isinstance(xmp_data, bytes):
                        return xmp_data.decode("utf-8", errors="ignore")
                    return str(xmp_data)
        except (OSError, ValueError):
            pass

        return ""

    def _display_xmp(self) -> None:
        """Display XMP data in the text widget."""
        self.xmp_text.config(state=tk.NORMAL)
        self.xmp_text.delete("1.0", tk.END)

        if self.xmp_data:
            # Display the XMP as-is (it's already formatted from the source)
            self.xmp_text.insert(tk.END, self.xmp_data)
        else:
            self.xmp_text.insert(tk.END, "No XMP data found.")

    @staticmethod
    def _pretty_print_xml(xml_string: str) -> str:
        """Add indentation to XML string for readability."""
        try:
            root = ET.fromstring(xml_string)
            return _indent_xml(root, 0)
        except ET.ParseError:
            return xml_string

    def _save_xmp(self, xmp_content: str) -> None:
        """Save XMP data back to the image file."""
        if not xmp_content.strip():
            return

        try:
            # Validate XMP XML structure
            ET.fromstring(xmp_content)

            # For JPEG, we need to write to the file
            if self.file_path.suffix.lower() in (".jpg", ".jpeg"):
                self._update_xmp_in_jpeg(xmp_content)
            elif self.file_path.suffix.lower() in (".png", ".tif", ".tiff"):
                self._update_xmp_in_png(xmp_content)
        except ET.ParseError as exc:
            error_msg = f"Invalid XMP XML format: {exc}"
            logger.error(error_msg)
            self._set_status(f"✗ {error_msg}", "red", 5000)
            raise ValueError(error_msg) from exc

    def _update_xmp_in_jpeg(self, xmp_content: str) -> None:
        """Update XMP in JPEG file."""
        try:
            with open(self.file_path, "rb") as f:
                data = bytearray(f.read())

            # Remove existing XMP APP1 marker if present
            i = 0
            xmp_start = None
            while i < len(data) - 9:
                if data[i : i + 2] == b"\xff\xe1":  # APP1 marker
                    length = int.from_bytes(bytes(data[i + 2 : i + 4]), "big")
                    app1_data = bytes(data[i + 4 : i + 4 + length - 2])

                    # Check for both XMP header variants
                    if b"adobe.com/xap" in app1_data or b"adobe:ns:meta" in app1_data:
                        xmp_start = i
                        xmp_end = i + length + 2
                        del data[xmp_start:xmp_end]
                        break
                    else:
                        i += length + 2
                else:
                    i += 1

            # Add new XMP data as APP1 marker
            xmp_bytes = xmp_content.encode("utf-8")
            xmp_header = b"http://ns.adobe.com/xap/1.0/\x00"
            app1_content = xmp_header + xmp_bytes
            app1_length = len(app1_content) + 2
            app1_marker = b"\xff\xe1" + app1_length.to_bytes(2, "big") + app1_content

            # Insert after SOI marker (first two bytes)
            if len(data) > 2 and data[0:2] == b"\xff\xd8":
                data[2:2] = app1_marker

            with open(self.file_path, "wb") as f:
                f.write(data)
        except OSError as exc:
            logger.error("Failed to update JPEG XMP: %s", exc)
            raise OSError(str(exc)) from exc

    def _update_xmp_in_png(self, xmp_content: str) -> None:
        """Update XMP in PNG file."""
        try:
            with Image.open(self.file_path) as img:
                info = img.info.copy()
                info["XMP"] = xmp_content.encode("utf-8")
                # Ensure mapping keys are str for PIL save kwargs
                img.save(self.file_path, **cast(dict[str, Any], info))
        except OSError as exc:
            logger.error("Failed to update PNG XMP: %s", exc)
            raise OSError(str(exc)) from exc

    def _save_metadata(self) -> None:
        """Save EXIF and XMP changes back to the file."""
        try:
            self._set_status("Saving metadata...", "blue")

            # Save EXIF data
            text_content = self.exif_text.get("1.0", tk.END)
            edited_exif = self._parse_exif_text(text_content)
            if edited_exif:
                for ifd_name in ("0th", "Exif", "GPS", "1st"):
                    if ifd_name not in edited_exif:
                        edited_exif[ifd_name] = {}

                backup_path = self.file_path.with_suffix(self.file_path.suffix + ".bak")
                if not backup_path.exists():
                    shutil.copy2(self.file_path, backup_path)

                exif_bytes = piexif.dump(edited_exif)
                piexif.insert(exif_bytes, str(self.file_path))

            # Save XMP data
            xmp_content = self.xmp_text.get("1.0", tk.END).strip()
            if xmp_content:
                self._save_xmp(xmp_content)

            logger.info("Metadata saved successfully to %s", self.file_path)
            self._set_status("✓ Metadata saved successfully!", "green", 3000)
        except (OSError, ValueError) as exc:
            error_msg = f"Failed to save metadata: {exc}"
            logger.error(error_msg)
            self._set_status(f"✗ {error_msg}", "red", 5000)

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

    def _convert_exif_value(self, ifd_name: str, tag_id: int, value_str: str) -> Any:
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
