"""CrowdCurate slideshow package."""

from .app import main
from .controller import SlideshowController
from .model import SlideDeck, SlideItem
from .view import SlideshowView

__all__ = [
    "SlideDeck",
    "SlideItem",
    "SlideshowController",
    "SlideshowView",
    "main",
]
__version__ = "0.1.0"
