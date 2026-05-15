"""CrowdCurate slideshow package."""

from .app import main
from .controller import SlideshowController
from .model import SlideDeck, SlideItem
from .view import SlideshowView

__all__ = ["main", "SlideDeck", "SlideItem", "SlideshowController", "SlideshowView"]
__version__ = "0.1.0"
