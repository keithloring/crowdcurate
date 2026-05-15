from pathlib import Path

from PIL import Image

from crowdcurate.controller import SlideshowController
from crowdcurate.model import SlideDeck, SlideItem


class DummyView:  # pylint: disable=too-many-instance-attributes
    def __init__(self) -> None:
        self.controller: SlideshowController | None = None
        self.displayed: list[SlideItem] = []
        self.placeholder: str | None = None
        self.status: str | None = None
        self.play_button_text: str | None = None
        self.scheduled_id: str | None = None
        self.canceled_id: str | None = None
        self.image: Image.Image | None = None

    def set_controller(self, controller: SlideshowController) -> None:
        self.controller = controller

    def display_slide(self, slide: SlideItem, image: Image.Image) -> None:
        self.displayed.append(slide)
        self.image = image

    def show_placeholder(self, text: str) -> None:
        self.placeholder = text

    def update_status(self, text: str) -> None:
        self.status = text

    def update_play_button(self, playing: bool) -> None:
        self.play_button_text = "Pause" if playing else "Play"

    def schedule(self, delay_seconds: float, callback: object) -> str:
        self.scheduled_id = f"scheduled-{delay_seconds}"
        if callback is not None:
            pass
        return self.scheduled_id

    def cancel_scheduled(self, after_id: object) -> None:
        self.canceled_id = str(after_id)


def test_player_navigation(tmp_path: Path) -> None:
    for index in range(2):
        image_path = tmp_path / f"image_{index}.jpg"
        Image.new("RGB", (1, 1)).save(image_path, format="JPEG")

    deck = SlideDeck([tmp_path])
    view = DummyView()
    controller = SlideshowController(deck, view, interval_seconds=0.1)

    controller.show_current()
    assert view.displayed[-1].source.name == "image_0.jpg"
    assert view.status == "1/2 — image_0.jpg"

    controller.next_slide()
    assert view.displayed[-1].source.name == "image_1.jpg"
    assert view.status == "2/2 — image_1.jpg"

    controller.previous_slide()
    assert view.displayed[-1].source.name == "image_0.jpg"
    assert view.status == "1/2 — image_0.jpg"


def test_toggle_playback_schedules_and_stops(tmp_path: Path) -> None:
    image_path = tmp_path / "one.jpg"
    Image.new("RGB", (1, 1)).save(image_path, format="JPEG")
    deck = SlideDeck([tmp_path])
    view = DummyView()
    controller = SlideshowController(deck, view, interval_seconds=0.1)

    controller.toggle_playback()
    assert controller.is_playing is True
    assert view.play_button_text == "Pause"
    assert view.scheduled_id == "scheduled-0.1"

    controller.toggle_playback()
    assert controller.is_playing is False
    assert view.play_button_text == "Play"
    assert view.canceled_id == "scheduled-0.1"
