"""Tests that static asset resolution works in both normal and frozen modes.

Catches the _MEIPASS bug: PyInstaller onefile bundles datas in the extraction
dir, but Path(__file__) points into the PYZ archive. Without the _MEIPASS
fallback, the app serves stale/missing assets from the wrong location.
"""

from pathlib import Path
from unittest.mock import patch
import sys


STATIC_DIR = Path(__file__).resolve().parents[1] / "tidal_dl" / "gui" / "static"
REQUIRED_FILES = ["index.html", "routes.js", "app.js", "style.css"]


class TestStaticAssetsExist:
    """Static files required by the GUI are present on disk."""

    def test_static_dir_exists(self):
        assert STATIC_DIR.is_dir(), f"Static directory missing: {STATIC_DIR}"

    def test_required_files_present(self):
        for name in REQUIRED_FILES:
            assert (STATIC_DIR / name).is_file(), f"Missing: {STATIC_DIR / name}"


class TestStaticDirResolution:
    """create_app resolves _STATIC_DIR correctly in normal and frozen modes."""

    def test_normal_mode_resolves_to_real_static(self):
        from tidal_dl.gui import _STATIC_DIR
        assert _STATIC_DIR.is_dir()
        for name in REQUIRED_FILES:
            assert (_STATIC_DIR / name).is_file(), f"Missing in resolved dir: {name}"

    def test_frozen_mode_uses_meipass(self, tmp_path):
        """Simulate PyInstaller frozen env — _STATIC_DIR should use _MEIPASS."""
        # Create a fake _MEIPASS structure
        fake_static = tmp_path / "tidal_dl" / "gui" / "static"
        fake_static.mkdir(parents=True)
        (fake_static / "app.js").write_text("// frozen")

        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "_MEIPASS", str(tmp_path), create=True):
            # Re-import to trigger the resolution logic
            import importlib
            import tidal_dl.gui
            importlib.reload(tidal_dl.gui)
            resolved = tidal_dl.gui._STATIC_DIR
            assert str(resolved) == str(fake_static), \
                f"Frozen mode should use _MEIPASS, got: {resolved}"

        # Restore normal mode
        importlib.reload(tidal_dl.gui)


class TestAppJsFeatureMarkers:
    """app.js contains expected feature markers — catches stale bundle issues."""

    def test_has_csrf_token_handling(self):
        js = (STATIC_DIR / "app.js").read_text()
        assert "X-CSRF-Token" in js

    def test_has_media_session(self):
        js = (STATIC_DIR / "app.js").read_text()
        assert "mediaSession" in js, "Media Session API integration missing"

    def test_has_waveform_hires(self):
        js = (STATIC_DIR / "app.js").read_text()
        assert "_wfHires" in js, "Hires waveform animation missing"

    def test_has_queue_persistence(self):
        js = (STATIC_DIR / "app.js").read_text()
        assert "playerQueue" in js, "Queue persistence missing"

    def test_has_sleep_timer(self):
        js = (STATIC_DIR / "app.js").read_text()
        assert "_sleepTimerId" in js, "Sleep timer missing"

    def test_html_has_preload_audio(self):
        html = (STATIC_DIR / "index.html").read_text()
        assert "audio-preload" in html, "Preload audio element missing"

    def test_html_has_sleep_button(self):
        html = (STATIC_DIR / "index.html").read_text()
        assert "btn-sleep" in html, "Sleep timer button missing"

    def test_html_loads_route_helper_before_app_js(self):
        html = (STATIC_DIR / "index.html").read_text()
        assert html.index('/routes.js') < html.index('/app.js')
