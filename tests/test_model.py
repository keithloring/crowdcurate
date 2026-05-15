from pathlib import Path

from crowdcurate.model import SlideDeck


def test_slide_deck_finds_image_files(tmp_path: Path) -> None:
    jpg_file = tmp_path / "image1.jpg"
    png_file = tmp_path / "image2.png"
    text_file = tmp_path / "notes.txt"

    jpg_file.write_bytes(b"fakejpeg")
    png_file.write_bytes(b"fakepng")
    text_file.write_text("ignore me")

    deck = SlideDeck([tmp_path])

    assert deck.size == 2
    assert deck.get_current() is not None
    assert deck.get_current().source.name == "image1.jpg"
    assert deck.move_next().source.name == "image2.png"
    assert deck.move_next().source.name == "image1.jpg"


def test_slide_deck_handles_missing_directory(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing"
    deck = SlideDeck()

    try:
        deck.add_directory(missing_path)
    except FileNotFoundError as exc:
        assert "Path does not exist" in str(exc)


def test_slide_deck_jump_to_index(tmp_path: Path) -> None:
    for index in range(3):
        (tmp_path / f"slide_{index}.jpg").write_bytes(b"fakeimage")

    deck = SlideDeck([tmp_path])
    target = deck.jump_to(2)

    assert target is not None
    assert target.source.name == "slide_2.jpg"
    assert deck.current_index == 2
