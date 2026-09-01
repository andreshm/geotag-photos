"""map_widget.py — Embedded Leaflet map with Dark Matter tiles, coordinate bar, and safe IPC bridge."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, Slot, QObject, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame,
)

from resources.theme import Colors, STYLE_MODERN_CYBER
from .photo_item import PhotoItem

log = logging.getLogger(__name__)

MAP_HTML = Path(__file__).parent.parent / "resources" / "map.html"


class MapBridge(QObject):
    """Exposed to JavaScript as `pyBridge`."""
    location_selected = Signal(float, float, str)
    photo_marker_clicked = Signal(str, float, float)

    @Slot(float, float, str)
    def locationSelected(self, lat: float, lon: float, label: str):
        self.location_selected.emit(lat, lon, label)

    @Slot(str, float, float)
    def photoMarkerClicked(self, identifier: str, lat: float, lon: float):
        self.photo_marker_clicked.emit(identifier, lat, lon)


class SilentPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        log.debug("[Map JS] %s (line %d)", message, line)


class MapWidget(QWidget):
    """Full-featured cyber-dark Leaflet map with Nominatim geocoding and manual coordinate input."""

    location_picked      = Signal(float, float, str)
    photo_marker_clicked = Signal(str, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._current_lat: Optional[float] = None
        self._current_lon: Optional[float] = None
        self._ready = False
        self._pending_js: list[str] = []

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── WebEngine View ───────────────────────────────────────────────────
        self._page = SilentPage(self)
        self._page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )

        self._view = QWebEngineView(self)
        self._view.setPage(self._page)

        self._bridge = MapBridge(self)
        self._bridge.location_selected.connect(self._on_location_selected)
        self._bridge.photo_marker_clicked.connect(self.photo_marker_clicked)

        self._channel = QWebChannel(self._page)
        self._channel.registerObject("pyBridge", self._bridge)
        self._page.setWebChannel(self._channel)

        if MAP_HTML.exists():
            self._page.loadFinished.connect(self._on_load_finished)
            self._view.setUrl(QUrl.fromLocalFile(str(MAP_HTML)))
        else:
            lbl = QLabel(f"⚠️ map.html not found at:\n{MAP_HTML}", self)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)
            return

        layout.addWidget(self._view, stretch=1)

        # ── Manual Coordinate Input Bar ──────────────────────────────────────
        coord_bar = QFrame(self)
        coord_bar.setStyleSheet(
            f"background: {Colors.BG_PANEL}; border-top: 1px solid {Colors.BORDER_DEFAULT};"
        )
        coord_bar.setFixedHeight(36)
        cb_lay = QHBoxLayout(coord_bar)
        cb_lay.setContentsMargins(8, 2, 8, 2)
        cb_lay.setSpacing(6)

        lbl_pin = QLabel("📌", coord_bar)
        cb_lay.addWidget(lbl_pin)

        self._input_coords = QLineEdit(coord_bar)
        self._input_coords.setPlaceholderText("Paste coordinates (e.g. 40.7128, -74.0060) or Google Maps URL...")
        self._input_coords.returnPressed.connect(self._parse_and_set_coords)
        cb_lay.addWidget(self._input_coords, stretch=1)

        self._btn_go = QPushButton("Set Pin", coord_bar)
        self._btn_go.setFixedWidth(70)
        self._btn_go.clicked.connect(self._parse_and_set_coords)
        cb_lay.addWidget(self._btn_go)

        self._btn_clear = QPushButton("Clear", coord_bar)
        self._btn_clear.setFixedWidth(55)
        self._btn_clear.clicked.connect(self.clear_picker)
        cb_lay.addWidget(self._btn_clear)

        layout.addWidget(coord_bar)

    # ── Internal Event Handlers ───────────────────────────────────────────────

    def _on_load_finished(self, ok: bool):
        if not ok:
            log.error("Map HTML failed to load")
            return
        self._ready = True
        for js in self._pending_js:
            self._page.runJavaScript(js)
        self._pending_js.clear()

    def _run_js(self, js: str):
        if self._ready:
            self._page.runJavaScript(js)
        else:
            self._pending_js.append(js)

    def _on_location_selected(self, lat: float, lon: float, label: str):
        self._current_lat = lat
        self._current_lon = lon
        self._input_coords.setText(f"{lat:.6f}, {lon:.6f}")
        self.location_picked.emit(lat, lon, label)

    # ── Coordinate parsing ────────────────────────────────────────────────────

    def _parse_and_set_coords(self):
        text = self._input_coords.text().strip()
        if not text:
            return

        coords = self._extract_lat_lon(text)
        if coords:
            lat, lon = coords
            self.set_picker(lat, lon)
            self._on_location_selected(lat, lon, "Manual Input")
        else:
            self._input_coords.setStyleSheet("border-color: #f43f5e;")

    def _extract_lat_lon(self, text: str) -> Optional[tuple[float, float]]:
        # 1. Decimal coordinate match: "40.7128, -74.0060"
        m = re.search(r"([-+]?\d{1,3}(?:\.\d+)?)\s*[,;\s]\s*([-+]?\d{1,3}(?:\.\d+)?)", text)
        if m:
            try:
                lat = float(m.group(1))
                lon = float(m.group(2))
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    return lat, lon
            except ValueError:
                pass

        # 2. Google Maps URL (@lat,lon or ?q=lat,lon)
        m2 = re.search(r"@([-+]?\d{1,3}\.\d+),([-+]?\d{1,3}\.\d+)", text)
        if m2:
            try:
                lat = float(m2.group(1))
                lon = float(m2.group(2))
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    return lat, lon
            except ValueError:
                pass

        return None

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def current_gps(self) -> Optional[tuple[float, float]]:
        if self._current_lat is not None and self._current_lon is not None:
            return (self._current_lat, self._current_lon)
        return None

    def clear_picker(self):
        self._current_lat = None
        self._current_lon = None
        self._input_coords.clear()
        self._input_coords.setStyleSheet("")
        self._run_js("clearPicker();")

    def fly_to(self, lat: float, lon: float, zoom: int = 15):
        self._run_js(f"flyTo({lat}, {lon}, {zoom});")

    def set_picker(self, lat: float, lon: float):
        self._current_lat = lat
        self._current_lon = lon
        self._input_coords.setText(f"{lat:.6f}, {lon:.6f}")
        self._input_coords.setStyleSheet("")
        self._run_js(f"setPicker({lat}, {lon});")

    def show_photo_markers(self, items: list[PhotoItem]):
        """Plot all photos safely without JS injection string escaping errors."""
        markers = []
        for item in items:
            g = item.effective_gps
            if g:
                markers.append({
                    "lat": g[0],
                    "lon": g[1],
                    "label": item.display_name,
                    "path": str(item.display_path.resolve()),
                    "isPending": item.pending.gps is not None,
                })

        payload = json.dumps(markers)
        self._run_js(f"setPhotoMarkersData({payload});")
