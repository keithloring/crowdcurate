import io
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import patch

from PIL import Image, ImageTk

from crowdcurate.cache import ThumbnailCache
from crowdcurate.sequence import Sequence, SequencePanel, SequenceStore


def test_sequence_save_load(tmp_path):
    store_dir = tmp_path / "store"
    store = SequenceStore(base_dir=store_dir)
    seq = Sequence(name="TestSeq", items=[Path("/tmp/a.jpg"), Path("/tmp/b.jpg")])
    saved = store.save(seq)
    assert saved.exists()
    loaded = store.load("TestSeq")
    assert loaded is not None
    assert loaded.name == "TestSeq"
    assert [str(p) for p in loaded.items] == [str(Path("/tmp/a.jpg")), str(Path("/tmp/b.jpg"))]


def test_sequence_panel_uses_real_thumbnail_images_before_async_cache_fills():
    root = tk.Tk()
    root.withdraw()
    try:
        class PlaceholderCache:
            def __init__(self):
                self._cache = {}

            def get_photo(self, path, max_size=(120, 80), on_ready=None):
                img = Image.new("RGB", max_size, (200, 200, 200))
                photo = ImageTk.PhotoImage(img)
                self._cache[str(path)] = photo
                return photo

        class DummyController:
            def __init__(self, image_path):
                self.current_sequence = Sequence(name="Demo", items=[])
                self.thumbnail_cache = PlaceholderCache()
                self.cache = type("Cache", (), {"get_thumbnail": lambda self, slide, max_size=(120, 80): Image.open(slide.source).copy()})()
                self._image_path = image_path

            def get_source_slides(self):
                return []

        p = Path(tempfile.mkdtemp()) / "thumb.png"
        Image.new("RGB", (200, 150), "blue").save(p)

        panel = SequencePanel(root, DummyController(p))
        photo = panel._load_photo(p, (120, 80))

        assert photo is not None
        assert photo.width() > 0
        assert photo.height() > 0
    finally:
        root.destroy()


def test_thumbnail_cache_uses_unique_placeholder_per_path():
    root = tk.Tk()
    root.withdraw()
    try:
        cache = ThumbnailCache(root)
        first = cache.get_photo(Path("/tmp/a.png"))
        second = cache.get_photo(Path("/tmp/b.png"))
        assert first is not second
        cache.shutdown()
    finally:
        root.destroy()


def test_thumbnail_cache_keeps_on_ready_callbacks_for_inflight_paths():
    root = tk.Tk()
    root.withdraw()
    try:
        cache = ThumbnailCache(root)
        p = Path(tempfile.mkdtemp()) / "inflight.png"
        Image.new("RGB", (64, 64), "green").save(p)

        seen = []

        def callback(path, photo):
            seen.append((str(path), photo is not None))

        first = cache.get_photo(p, max_size=(32, 32), on_ready=callback)
        second = cache.get_photo(p, max_size=(32, 32), on_ready=callback)

        assert first is not None
        assert second is not None

        def finish():
            root.quit()

        root.after(250, finish)
        root.mainloop()

        assert len(seen) == 2
        assert all(str(path) == str(p) for path, _ in seen)
        cache.shutdown()
    finally:
        root.destroy()


def test_sequence_panel_highlights_current_source_thumbnail_and_click_selects_it():
    root = tk.Tk()
    root.withdraw()
    try:
        class DummyController:
            def __init__(self):
                self.current_sequence = Sequence(name="Demo", items=[])
                self.deck = type("Deck", (), {"slides": [], "current_index": 0, "get_current": lambda self: self.slides[self.current_index] if self.slides else None})()
                self.deck.slides = [
                    type("Slide", (), {"source": Path(__file__).with_name("alpha.png")})(),
                    type("Slide", (), {"source": Path(__file__).with_name("beta.png")})(),
                ]

            def get_source_slides(self):
                return self.deck.slides

            def jump_to(self, index):
                self.deck.current_index = index

        controller = DummyController()
        panel = SequencePanel(root, controller)

        controller.deck.current_index = 1
        panel.refresh()

        selected = panel._source_widgets[str(controller.deck.get_current().source)]
        assert selected.cget("highlightthickness") > 0
        assert selected.cget("relief") == "solid"

        panel._select_source_slide(controller.deck.slides[0])
        assert controller.deck.current_index == 0
    finally:
        root.destroy()


def test_source_click_only_updates_selection_without_full_refresh():
    root = tk.Tk()
    root.withdraw()
    try:
        class DummyController:
            def __init__(self):
                self.current_sequence = Sequence(name="Demo", items=[])
                self._slides = [
                    type("Slide", (), {"source": Path(__file__).with_name("alpha.png")})(),
                    type("Slide", (), {"source": Path(__file__).with_name("beta.png")})(),
                ]
                self.deck = type("Deck", (), {"current_index": 0, "get_current": lambda self: self._slides[self.current_index]})()
                self.deck._slides = self._slides

            def get_source_slides(self):
                return self._slides

            def jump_to(self, index):
                self.deck.current_index = index

        controller = DummyController()
        panel = SequencePanel(root, controller)
        panel._source_widgets = {
            str(controller._slides[0].source): tk.Label(root),
            str(controller._slides[1].source): tk.Label(root),
        }

        calls = []
        original = SequencePanel.refresh

        def tracking(self):
            calls.append("refresh")
            return original(self)

        SequencePanel.refresh = tracking
        try:
            panel._select_source_slide(controller._slides[1])
            assert controller.deck.current_index == 1
            assert calls == []
        finally:
            SequencePanel.refresh = original
    finally:
        root.destroy()


def test_source_panel_scroll_position_is_preserved_on_selection_refresh():
    root = tk.Tk()
    root.withdraw()
    try:
        class DummyController:
            def __init__(self):
                self.current_sequence = Sequence(name="Demo", items=[])
                self._slides = [
                    type("Slide", (), {"source": Path(__file__).with_name(f"img{i}.png")})()
                    for i in range(20)
                ]
                self.deck = type("Deck", (), {"current_index": 0, "get_current": lambda self: self._slides[self.current_index]})()
                self.deck._slides = self._slides

            def get_source_slides(self):
                return self._slides

            def jump_to(self, index):
                self.deck.current_index = index

        controller = DummyController()
        panel = SequencePanel(root, controller)
        panel.show()
        root.update_idletasks()
        panel._source_canvas.xview_moveto(0.75)
        root.update_idletasks()
        panel._populate_source()

        assert abs(float(panel._source_canvas.xview()[0]) - 0.75) < 0.2
    finally:
        root.destroy()


def test_source_panel_scrolls_selected_thumbnail_into_view():
    root = tk.Tk()
    root.withdraw()
    try:
        class DummyController:
            def __init__(self):
                self.current_sequence = Sequence(name="Demo", items=[])
                self._slides = [
                    type("Slide", (), {"source": Path(__file__).with_name(f"source_{i}.png")})()
                    for i in range(20)
                ]
                self.deck = type("Deck", (), {"current_index": 19, "get_current": lambda self: self._slides[self.current_index]})()
                self.deck._slides = self._slides

            def get_source_slides(self):
                return self._slides

            def jump_to(self, index):
                self.deck.current_index = index

        controller = DummyController()
        panel = SequencePanel(root, controller)
        panel.show()
        root.update_idletasks()
        panel._source_canvas.xview_moveto(0.0)
        root.update_idletasks()

        panel._last_source_selection_key = str(controller._slides[0].source)
        controller.deck.current_index = 19
        panel._update_source_selection_state()
        root.update_idletasks()

        assert float(panel._source_canvas.xview()[0]) > 0.0
    finally:
        root.destroy()


def test_sequence_panel_scroll_position_is_preserved_on_refresh():
    root = tk.Tk()
    root.withdraw()
    try:
        class DummyController:
            def __init__(self):
                self.current_sequence = Sequence(name="Demo", items=[Path("/tmp/a.png"), Path("/tmp/b.png")])

        controller = DummyController()
        panel = SequencePanel(root, controller)
        panel.show()
        root.update_idletasks()
        panel._sequence_canvas.xview_moveto(0.75)
        root.update_idletasks()

        panel._populate_sequence()
        root.update_idletasks()

        assert float(panel._sequence_canvas.xview()[0]) > 0.0
    finally:
        root.destroy()


def test_active_source_drag_is_not_interrupted_by_sequence_drag_start():
    root = tk.Tk()
    root.withdraw()
    try:
        class DummyController:
            def __init__(self):
                self.current_sequence = Sequence(name="Demo", items=[Path("/tmp/seq.png")])

        panel = SequencePanel(root, DummyController())
        source_slide = type("Slide", (), {"source": Path("/tmp/source.png")})()
        panel._dragging = True
        panel._drag_source_path = source_slide.source
        panel._drag_from_index = None

        panel._start_drag_sequence(None, 0)

        assert panel._dragging is True
        assert panel._drag_source_path == source_slide.source
        assert panel._drag_from_index is None
    finally:
        root.destroy()


def test_sequence_panel_shows_drop_cursor_while_dragging():
    root = tk.Tk()
    root.withdraw()
    try:
        class DummyController:
            def __init__(self):
                self.current_sequence = Sequence(name="Demo", items=[Path("/tmp/a.png"), Path("/tmp/b.png")])

        panel = SequencePanel(root, DummyController())
        panel.show()
        root.update_idletasks()
        panel._dragging = True
        panel._drag_moved = True
        panel._drag_ghost = None
        event = type("Event", (), {"x_root": root.winfo_rootx() + 180, "y_root": root.winfo_rooty() + 60})()

        panel._on_drag_motion(event)

        assert panel._sequence_drop_cursor_id is not None
        cursor_x = panel._sequence_canvas.coords(panel._sequence_drop_cursor_id)[0]
        assert cursor_x == 134.0
    finally:
        root.destroy()


def test_sequence_panel_reorder_drag_binds_to_thumbnails():
    root = tk.Tk()
    root.withdraw()
    try:
        class DummyController:
            def __init__(self):
                self.current_sequence = Sequence(name="Demo", items=[Path("/tmp/a.png"), Path("/tmp/b.png")])

        panel = SequencePanel(root, DummyController())
        panel._populate_sequence()
        root.update_idletasks()

        bound_widget_count = 0
        for item_id in panel._sequence_canvas.find_all():
            window_name = panel._sequence_canvas.itemcget(item_id, "window")
            if not window_name:
                continue
            window = panel._sequence_canvas.nametowidget(window_name)
            label = window.winfo_children()[0]
            if label.bind("<ButtonPress-1>"):
                bound_widget_count += 1

        assert bound_widget_count >= 2
    finally:
        root.destroy()


def test_sequence_panel_populates_without_reorder_buttons():
    root = tk.Tk()
    root.withdraw()
    try:
        class DummyController:
            def __init__(self):
                self.current_sequence = Sequence(name="Demo", items=[Path("/tmp/a.png"), Path("/tmp/b.png")])

        controller = DummyController()
        panel = SequencePanel(root, controller)

        with patch("crowdcurate.sequence.ttk.Button") as button_mock:
            panel._populate_sequence()

        assert button_mock.call_count == 0
    finally:
        root.destroy()


def test_sequence_panel_export_video_uses_sequence_images():
    root = tk.Tk()
    root.withdraw()
    try:
        temp_dir = Path(tempfile.mkdtemp())
        image_one = temp_dir / "a.png"
        image_two = temp_dir / "b.png"
        Image.new("RGB", (32, 32), "red").save(image_one)
        Image.new("RGB", (32, 32), "blue").save(image_two)

        class DummyController:
            def __init__(self):
                self.current_sequence = Sequence(
                    name="Demo",
                    items=[image_one, image_two],
                )

        panel = SequencePanel(root, DummyController())
        out_path = temp_dir / "out.mp4"

        seen = {}

        class FakeProcess:
            def __init__(self, cmd):
                self.cmd = cmd
                self.stdout = io.StringIO("frame=000012 fps=30.0 q=27.0 size=...\n")
                self.returncode = 0

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                return self.returncode

            def terminate(self):
                self.returncode = 0

        def fake_popen(cmd, *args, **kwargs):
            list_path = next(arg for arg in cmd if arg.endswith(".txt"))
            list_text = Path(list_path).read_text(encoding="utf-8")
            assert "duration 2.0" in list_text
            assert "duration 0.037" in list_text
            seen["cmd"] = cmd
            return FakeProcess(cmd)

        with patch("crowdcurate.sequence.filedialog.asksaveasfilename", return_value=str(out_path)), patch("crowdcurate.sequence.subprocess.Popen", side_effect=fake_popen) as popen_mock, patch("crowdcurate.sequence.threading.Thread.start", return_value=None):
            panel._export_sequence_video()

        assert popen_mock.call_count == 1
        cmd = seen["cmd"]
        assert cmd[0] == "ffmpeg"
        assert "-y" in cmd
        assert "-f" in cmd
        assert "concat" in cmd
        assert "-safe" in cmd
        assert "0" in cmd
        assert "-i" in cmd
        assert str(out_path) in cmd
    finally:
        root.destroy()


def test_ffmpeg_progress_parser_tracks_generated_frame_count():
    root = tk.Tk()
    root.withdraw()
    try:
        class DummyController:
            def __init__(self):
                self.current_sequence = Sequence(name="Demo", items=[])

        panel = SequencePanel(root, DummyController())

        assert panel._parse_ffmpeg_progress("frame=000012 fps=30.0 q=27.0 size=...", total_frames=24) == 50.0
        assert panel._parse_ffmpeg_progress("frame=000024 fps=30.0 q=27.0 size=...", total_frames=24) == 100.0
        assert panel._parse_ffmpeg_progress("some unrelated line", total_frames=24) is None
    finally:
        root.destroy()


def test_play_exported_video_uses_vlc():
    root = tk.Tk()
    root.withdraw()
    try:
        class DummyController:
            def __init__(self):
                self.current_sequence = Sequence(name="Demo", items=[])

        panel = SequencePanel(root, DummyController())
        output_path = Path(tempfile.mkdtemp()) / "demo.mp4"

        with patch("crowdcurate.sequence.subprocess.Popen") as popen_mock:
            panel._play_exported_video(output_path)

        popen_mock.assert_called_once()
        cmd = popen_mock.call_args[0][0]
        assert cmd[0] == "vlc"
        assert str(output_path) in cmd
    finally:
        root.destroy()


def test_export_progress_spans_preparation_and_ffmpeg_runtime():
    root = tk.Tk()
    root.withdraw()
    try:
        panel = SequencePanel(root, type("DummyController", (), {"current_sequence": Sequence(name="Demo", items=[]), "get_source_slides": lambda self: []})())

        assert panel._combine_export_progress(50.0, 85.0) == 92.5
        assert panel._combine_export_progress(100.0, 85.0) == 100.0
    finally:
        root.destroy()


def test_sequence_panel_show_refreshes_once():
    root = tk.Tk()
    root.withdraw()
    try:
        class DummyController:
            def __init__(self):
                self.current_sequence = Sequence(name="Demo", items=[])

            def get_source_slides(self):
                return []

        controller = DummyController()
        panel = SequencePanel(root, controller)
        calls = []
        original = SequencePanel.refresh

        def tracking(self):
            calls.append("refresh")
            return original(self)

        SequencePanel.refresh = tracking
        try:
            panel.show()
            root.update_idletasks()
            assert calls == ["refresh"]
        finally:
            SequencePanel.refresh = original
    finally:
        root.destroy()


def test_sequence_redraw_does_not_force_nested_tk_updates():
    root = tk.Tk()
    root.withdraw()
    try:
        class DummyController:
            def __init__(self):
                self.current_sequence = Sequence(name="Demo", items=[])

            def get_source_slides(self):
                return []

        panel = SequencePanel(root, DummyController())

        class GuardCanvas(tk.Canvas):
            def update(self):
                raise AssertionError("nested Tk update() should not run during redraw")

        panel._source_canvas = GuardCanvas(root)
        panel._source_canvas.pack()

        panel._redraw_canvas(panel._source_canvas)
    finally:
        root.destroy()