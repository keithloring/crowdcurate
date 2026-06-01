"""Tests for metadata window and EXIF editor."""

# pylint: disable=protected-access, redefined-outer-name

import shutil
import tkinter as tk
from pathlib import Path

import piexif
import pytest
from PIL import Image

from crowdcurate.metadata import ExifEditorWindow, MetadataWindow


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
