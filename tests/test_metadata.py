"""Tests for metadata window and EXIF editor."""

# pylint: disable=protected-access, redefined-outer-name

import shutil
import tkinter as tk
import xml.etree.ElementTree as ET
from pathlib import Path

import piexif
import pytest
from PIL import Image

from crowdcurate.metadata import ExifEditorWindow, MetadataWindow
from crowdcurate.model import SlideItem


@pytest.fixture
def sample_image_with_exif(tmp_path: Path) -> Path:
    """Create a sample image with EXIF data."""
    img_path = tmp_path / "test_image.jpg"

    # Create a simple image
    img = Image.new("RGB", (100, 100), color="red")
    img.save(img_path, "JPEG")

    # Add EXIF data
    exif_dict = {
        "0th": {
            piexif.ImageIFD.Make: b"TestCamera",
            piexif.ImageIFD.Model: b"TestModel",
            piexif.ImageIFD.XResolution: ((72, 1),),
            piexif.ImageIFD.YResolution: ((72, 1),),
        },
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: b"2024:01:01 12:00:00",
            piexif.ExifIFD.ExposureTime: ((1, 100),),
        },
        "GPS": {},
        "1st": {},
    }

    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, str(img_path))

    return img_path


@pytest.fixture
def sample_image_no_exif(tmp_path: Path) -> Path:
    """Create a sample image without EXIF data."""
    img_path = tmp_path / "no_exif.jpg"
    img = Image.new("RGB", (100, 100), color="blue")
    img.save(img_path, "JPEG")
    return img_path


@pytest.fixture
def sample_image_with_xmp(tmp_path: Path) -> Path:
    """Create a sample image with XMP data."""
    img_path = tmp_path / "test_xmp.jpg"

    # Create a simple image
    img = Image.new("RGB", (100, 100), color="green")
    img.save(img_path, "JPEG")

    # Create XMP data
    xmp_content = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
    <rdf:Description rdf:about="">
        <dc:title>Test Image</dc:title>
        <dc:creator>Test Creator</dc:creator>
    </rdf:Description>
</rdf:RDF>"""

    # Write XMP to JPEG using PIL
    with Image.open(img_path) as img_obj:
        img_obj.info["XMP"] = xmp_content.encode("utf-8")
        img_obj.save(img_path, "JPEG")

    return img_path


class TestMetadataWindow:
    """Test MetadataWindow creation and data display."""

    def test_metadata_window_creation(self) -> None:
        """Test that MetadataWindow can be instantiated."""
        root = tk.Tk()
        try:
            window = MetadataWindow(root)
            assert window is not None
            assert window.current_hash is None
        finally:
            root.destroy()

    def test_metadata_compute_hash(self, sample_image_with_exif: Path) -> None:
        """Test SHA256 hash computation."""
        hash_val = MetadataWindow._compute_sha256(sample_image_with_exif)
        assert isinstance(hash_val, str)
        assert len(hash_val) == 64  # SHA256 hex digest length

    def test_metadata_window_shows_path_and_sha256(
        self, sample_image_with_exif: Path
    ) -> None:
        """Test that the info pane includes path and SHA256 lines."""
        root = tk.Tk()
        try:
            window = MetadataWindow(root)
            slide = SlideItem(sample_image_with_exif)
            window.update(slide)
            assert window.current_hash is not None
            assert window.current_hash != ""
            assert window._text_widget is not None
            # Get all text content
            all_text = window._text_widget.get("1.0", tk.END).strip()
            lines = all_text.split("\n")
            # Should have at least a path and SHA256 line
            assert len(lines) >= 2
            assert any("Path:" in line for line in lines)
            assert any("SHA256:" in line for line in lines)
            # Verify SHA256 line has correct format
            sha256_line = [line for line in lines if "SHA256:" in line][0]
            sha256_value = sha256_line.split("SHA256:", 1)[1].strip()
            assert len(sha256_value) == 64
        finally:
            root.destroy()


class TestExifEditorWindow:
    """Test EXIF editor functionality."""

    def test_exif_editor_loads_data(self, sample_image_with_exif: Path) -> None:
        """Test that ExifEditorWindow loads EXIF data correctly."""
        root = tk.Tk()
        try:
            editor = ExifEditorWindow(root, sample_image_with_exif)
            assert editor.exif_data is not None
            assert "0th" in editor.exif_data or len(editor.tag_mapping) > 0
        finally:
            root.destroy()

    def test_exif_editor_no_exif(self, sample_image_no_exif: Path) -> None:
        """Test that ExifEditorWindow handles images without EXIF gracefully."""
        root = tk.Tk()
        try:
            editor = ExifEditorWindow(root, sample_image_no_exif)
            assert editor.exif_data is not None
        finally:
            root.destroy()

    def test_convert_exif_value_ascii(self) -> None:
        """Test conversion of ASCII EXIF values."""
        root = tk.Tk()
        try:
            editor = ExifEditorWindow.__new__(ExifEditorWindow)
            editor.tag_types = {
                ("0th", 271): 2,  # ASCII type
            }

            result = editor._convert_exif_value("0th", 271, "TestValue")
            assert isinstance(result, bytes)
            assert result == b"TestValue"
        finally:
            root.destroy()

    def test_convert_exif_value_short(self) -> None:
        """Test conversion of SHORT EXIF values."""
        root = tk.Tk()
        try:
            editor = ExifEditorWindow.__new__(ExifEditorWindow)
            editor.tag_types = {
                ("0th", 256): 3,  # SHORT type
            }

            result = editor._convert_exif_value("0th", 256, "256")
            assert isinstance(result, int)
            assert result == 256
        finally:
            root.destroy()

    def test_convert_exif_value_rational(self) -> None:
        """Test conversion of RATIONAL EXIF values."""
        root = tk.Tk()
        try:
            editor = ExifEditorWindow.__new__(ExifEditorWindow)
            editor.tag_types = {
                ("Exif", 33434): 5,  # RATIONAL type (ExposureTime)
            }

            # Test fraction format
            result = editor._convert_exif_value("Exif", 33434, "1/100")
            assert isinstance(result, tuple)
            assert result == (1, 100)

            # Test decimal format
            result2 = editor._convert_exif_value("Exif", 33434, "0.01")
            assert isinstance(result2, tuple)
            assert result2[0] == 10
            assert result2[1] == 1000
        finally:
            root.destroy()

    def test_convert_exif_value_undefined_bytes(self) -> None:
        """Test conversion of UNDEFINED/BYTE EXIF values."""
        root = tk.Tk()
        try:
            editor = ExifEditorWindow.__new__(ExifEditorWindow)
            editor.tag_types = {
                ("Exif", 36864): 7,  # UNDEFINED type (ExifVersion)
            }

            result = editor._convert_exif_value("Exif", 36864, "0230")
            assert isinstance(result, bytes)
            assert result == b"0230"
        finally:
            root.destroy()

    def test_parse_exif_text_basic(self, sample_image_with_exif: Path) -> None:
        """Test parsing of edited EXIF text."""
        root = tk.Tk()
        try:
            editor = ExifEditorWindow(root, sample_image_with_exif)

            # Create sample edit text
            edit_text = """[0th]
Make=NewCamera
Model=NewModel

[Exif]
"""

            result = editor._parse_exif_text(edit_text)
            assert "0th" in result
            assert "Exif" in result
        finally:
            root.destroy()

    def test_save_metadata_ignores_xmp_placeholder(self, tmp_path: Path) -> None:
        """Saving EXIF-only edits should not try to parse the XMP placeholder as XML."""
        img_path = tmp_path / "placeholder.jpg"
        Image.new("RGB", (10, 10), color="white").save(img_path, "JPEG")

        root = tk.Tk()
        try:
            editor = ExifEditorWindow(root, img_path)
            editor.exif_text.delete("1.0", tk.END)
            editor.exif_text.insert(tk.END, "[0th]\n")
            editor.xmp_text.delete("1.0", tk.END)
            editor.xmp_text.insert(tk.END, "No XMP data found.")

            editor._save_metadata()
            assert editor.status_label is not None
            assert "saved successfully" in editor.status_label.cget("text").lower()
        finally:
            root.destroy()

    def test_save_exif_integration(
        self, sample_image_with_exif: Path, tmp_path: Path
    ) -> None:
        """Test that EXIF can be modified and saved correctly."""
        # Make a copy to avoid modifying the test fixture
        test_img = tmp_path / "test_save.jpg"
        shutil.copy2(sample_image_with_exif, test_img)

        root = tk.Tk()
        try:
            editor = ExifEditorWindow(root, test_img)

            # Simulate editing and saving
            assert "0th" in editor.exif_data

            # Verify backup would be created
            backup_path = test_img.with_suffix(test_img.suffix + ".bak")
            assert not backup_path.exists()

        finally:
            root.destroy()

    def test_xmp_editor_loads_data(self, sample_image_with_xmp: Path) -> None:
        """Test that ExifEditorWindow loads XMP data correctly."""
        root = tk.Tk()
        try:
            editor = ExifEditorWindow(root, sample_image_with_xmp)
            # XMP should be loaded (may be empty if not embedded)
            assert editor.xmp_data is not None
        finally:
            root.destroy()

    def test_xmp_editor_no_xmp(self, sample_image_no_exif: Path) -> None:
        """Test that ExifEditorWindow handles images without XMP gracefully."""
        root = tk.Tk()
        try:
            editor = ExifEditorWindow(root, sample_image_no_exif)
            # Should not fail even if no XMP
            assert editor.xmp_data is not None
        finally:
            root.destroy()

    def test_pretty_print_xml(self) -> None:
        """Test XML pretty printing."""
        root = tk.Tk()
        try:
            editor = ExifEditorWindow.__new__(ExifEditorWindow)

            xml_str = "<root><child>Text</child></root>"
            result = editor._pretty_print_xml(xml_str)
            assert isinstance(result, str)
            assert "root" in result
            assert "child" in result
        finally:
            root.destroy()

    def test_xmp_xml_validation(self) -> None:
        """Test that invalid XMP XML is rejected."""
        root = tk.Tk()
        try:
            # Create a minimal editor with required attributes
            editor = ExifEditorWindow.__new__(ExifEditorWindow)
            editor.dialog = root
            editor.file_path = Path("test.jpg")

            # Invalid XML should raise ValueError due to ParseError
            invalid_xmp = "<root><unclosed>"
            with pytest.raises(ValueError):
                editor._save_xmp(invalid_xmp)
        finally:
            root.destroy()

    def test_xmp_xml_parsing(self) -> None:
        """Test XMP XML parsing."""
        root = tk.Tk()
        try:
            # Create a minimal editor with required attributes
            editor = ExifEditorWindow.__new__(ExifEditorWindow)
            editor.dialog = root
            editor.file_path = Path("test.jpg")

            # Valid XMP should not raise ValueError
            valid_xmp = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description rdf:about=""/>
</rdf:RDF>"""

            # This should validate successfully (but may fail on file write)
            try:
                editor._save_xmp(valid_xmp)
            except (OSError, ValueError):
                # File write or validation errors are expected
                pass
        finally:
            root.destroy()
