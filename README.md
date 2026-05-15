# CrowdCurate

CrowdCurate is a Python 3.11 GUI slideshow application built with `tkinter` and a classic Model-View-Controller architecture.
It scans one or more directories for supported image formats, then lets users navigate, play, and pause a slideshow interactively.

## Features

- Loads images from directories recursively
- Supports `.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, and `.tiff`
- Simple MVC architecture for maintainability and testability
- Keyboard controls: left/right arrows and spacebar play/pause
- CLI entrypoint and package install support

## Install

```bash
python -m pip install -e .
```

## Run

```bash
crowdcurate ./images --interval 4.0 --title "My Slideshow"
```

Alternatively:

```bash
python -m crowdcurate ./images
```

## Development

Create and activate the virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install runtime and development dependencies:

```bash
python -m pip install -e .[dev]
```

Run tests:

```bash
python -m pytest
```

Run coverage:

```bash
python -m pytest --cov=crowdcurate tests
```

Run linters and format check:

```bash
ruff check src tests
pylint src tests
black --check src tests
```

This project is designed for modern Python best practices, with type hints, a clean package layout, and a lightweight CLI.
