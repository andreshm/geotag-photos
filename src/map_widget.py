"""map_widget.py — Leaflet map embedded via QWebEngineView + QWebChannel."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    Qt, Signal, Slot, QObject, QUrl, QTimer,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from .photo_item import PhotoItem

log = logging.getLogger(__name__)

MAP_HTML = Path(__file__).parent.parent / "resources" / "map.html"


# ──────────────────────────────────────────────────────────────────────────────
# Python ↔ JavaScript bridge object
# ──────────────────────────────────────────────────────────────────────────────

class MapBridge(QObject):
    """Exposed to JavaScript as `pyBridge`."""

    # Emitted when the user clicks / drags the picker on the map
    location_selected = Signal(float, float, str)   # lat, lon, label

    @Slot(float, float, str)
    def locationSelected(self, lat: float, lon: float, label: str):
        log.debug("Map → Python: lat=%.6f lon=%.6f label=%s", lat, lon, label)
        self.location_selected.emit(lat, lon, label)


# ──────────────────────────────────────────────────────────────────────────────
# Convenience page subclass (suppress noisy JS console spam)
# ──────────────────────────────────────────────────────────────────────────────

class SilentPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        lvl_map = {
            QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel:    logging.DEBUG,
            QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel: logging.WARNING,
            QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:   logging.ERROR,
        }
        log.log(lvl_map.get(level, logging.DEBUG), "[JS] %s (line %d, %s)", message, line, source)


# ──────────────────────────────────────────────────────────────────────────────
# Map widget
# ──────────────────────────────────────────────────────────────────────────────

class MapWidget(QWidget):
    """Full-featured Leaflet map with Nominatim search.

    Signals
    -------
    location_picked : (lat: float, lon: float, label: str)
        Fired whenever the user places/moves the orange picker marker.
    """

    location_picked = Signal(float, float, str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._current_lat: Optional[float] = None
        self._current_lon: Optional[float] = None
        self._ready = False           # True once the map JS has fully loaded
        self._pending_js: list[str] = []   # JS calls queued before ready

        # ── layout ────────────────────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── WebEngine ─────────────────────────────────────────────────────────
        self._page = SilentPage(self)
        self._view = QWebEngineView(self)
        self._view.setPage(self._page)

        # ── QWebChannel ───────────────────────────────────────────────────────
        self._bridge = MapBridge(self)
        self._bridge.location_selected.connect(self._on_location_selected)

        self._channel = QWebChannel(self._page)
        self._channel.registerObject("pyBridge", self._bridge)
        self._page.setWebChannel(self._channel)

        # ── Load the HTML ─────────────────────────────────────────────────────
        if MAP_HTML.exists():
            self._page.loadFinished.connect(self._on_load_finished)
            self._view.setUrl(QUrl.fromLocalFile(str(MAP_HTML)))
        else:
            lbl = QLabel(f"⚠️  map.html not found:\n{MAP_HTML}", self)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #ef4444; font-size: 13px;")
            layout.addWidget(lbl)
            return

        layout.addWidget(self._view)

    # ── internal slots ────────────────────────────────────────────────────────

    def _on_load_finished(self, ok: bool):
        if not ok:
            log.error("Map HTML failed to load")
            return
        self._ready = True
        log.debug("Map loaded OK — flushing %d queued JS calls", len(self._pending_js))
        for js in self._pending_js:
            self._page.runJavaScript(js)
        self._pending_js.clear()

    def _run_js(self, js: str):
        """Run JS immediately if ready, otherwise queue it."""
        if self._ready:
            self._page.runJavaScript(js)
        else:
            self._pending_js.append(js)

    def _on_location_selected(self, lat: float, lon: float, label: str):
        self._current_lat = lat
        self._current_lon = lon
        self.location_picked.emit(lat, lon, label)

    # ── public API ────────────────────────────────────────────────────────────

    @property
    def current_gps(self) -> Optional[tuple[float, float]]:
        if self._current_lat is not None and self._current_lon is not None:
            return (self._current_lat, self._current_lon)
        return None

    def clear_picker(self):
        """Remove the orange picker marker from the map."""
        self._current_lat = None
        self._current_lon = None
        self._run_js("clearPicker();")

    def fly_to(self, lat: float, lon: float, zoom: int = 14):
        """Pan and zoom the map to the given coordinates."""
        self._run_js(f"flyTo({lat}, {lon}, {zoom});")

    def set_picker(self, lat: float, lon: float):
        """Place the picker marker programmatically (e.g. show existing GPS)."""
        self._run_js(f"setPicker({lat}, {lon});")

    def show_photo_markers(self, items: list[PhotoItem]):
        """Draw blue dots on the map for all geotagged photos."""
        markers = []
        for item in items:
            g = item.effective_gps
            if g:
                markers.append({
                    "lat":   g[0],
                    "lon":   g[1],
                    "label": item.display_name,
                })
        js_data = json.dumps(markers).replace("'", "\\'")
        self._run_js(f"setPhotoMarkers('{js_data}');")

    def show_photo_markers_from_json(self, markers_json: str):
        escaped = markers_json.replace("'", "\\'")
        self._run_js(f"setPhotoMarkers('{escaped}');")
