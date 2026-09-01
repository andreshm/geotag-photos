"""photo_preview.py — Modern cyber-dark photo inspector and EXIF metadata panel."""

from __future__ import annotations

import os
import logging
import subprocess
import webbrowser
from typing import Optional

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPixmap, QColor, QPainter, QFont, QPen, QBrush, QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QFrame, QSizePolicy, QApplication,
    QGridLayout,
)

from resources.theme import Colors, STYLE_MODERN_CYBER
from .photo_item import PhotoItem
from .photo_manager import reverse_geocode

log = logging.getLogger(__name__)

PREVIEW_H = 150


class _ThumbFrame(QWidget):
    """Draws the thumbnail preview with subtle rounded border."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self.setFixedSize(PREVIEW_H - 12, PREVIEW_H - 12)

    def set_pixmap(self, px: Optional[QPixmap]):
        self._pixmap = px
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()

        painter.setBrush(QBrush(QColor("#070c18")))
        painter.setPen(QPen(QColor(Colors.BORDER_CARD), 1))
        painter.drawRoundedRect(r.adjusted(1, 1, -1, -1), 6, 6)

        if self._pixmap:
            scaled = self._pixmap.scaled(
                r.width() - 6, r.height() - 6,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = r.x() + (r.width() - scaled.width()) // 2
            y = r.y() + (r.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            painter.setPen(QColor(Colors.TEXT_MUTED))
            painter.setFont(QFont("Segoe UI", 24))
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, "📷")

        painter.end()


class PhotoInfoBar(QFrame):
    """A sleek cyber-dark panel showing the selected photo's detailed EXIF metadata and actions."""

    open_requested   = Signal(object)   # PhotoItem
    locate_requested = Signal(object)   # PhotoItem

    def __init__(self, parent=None):
        super().__init__(parent)
        self._item: Optional[PhotoItem] = None

        self.setFixedHeight(PREVIEW_H)
        self.setStyleSheet(
            f"PhotoInfoBar {{ background: {Colors.BG_PANEL}; border-top: 1px solid {Colors.BORDER_DEFAULT}; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(14)

        # ── Thumbnail ─────────────────────────────────────────────────────────
        self._thumb = _ThumbFrame(self)
        layout.addWidget(self._thumb)

        # ── Metadata Grid ─────────────────────────────────────────────────────
        meta_layout = QVBoxLayout()
        meta_layout.setSpacing(2)

        # Title Row: Name + Type Badge + Size
        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        self._lbl_name = QLabel("", self)
        self._lbl_name.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-size: 13px; font-weight: bold;")
        self._lbl_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._lbl_name.setMaximumWidth(420)
        title_row.addWidget(self._lbl_name, stretch=1)

        self._lbl_badge = QLabel("", self)
        self._lbl_badge.setStyleSheet(
            f"background: #082f49; color: {Colors.CYAN_LIGHT}; border: 1px solid {Colors.CYAN}; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: bold;"
        )
        title_row.addWidget(self._lbl_badge)

        self._lbl_size = QLabel("", self)
        self._lbl_size.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 11px;")
        title_row.addWidget(self._lbl_size)

        title_row.addStretch()
        meta_layout.addLayout(title_row)

        # 2-column info grid
        info_grid = QGridLayout()
        info_grid.setSpacing(3)
        info_grid.setContentsMargins(0, 2, 0, 2)

        # Row 0: Camera / Exposure
        self._lbl_camera = QLabel("", self)
        self._lbl_camera.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        info_grid.addWidget(self._lbl_camera, 0, 0)

        self._lbl_exposure = QLabel("", self)
        self._lbl_exposure.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        info_grid.addWidget(self._lbl_exposure, 0, 1)

        # Row 1: Date / Dimensions
        self._lbl_date = QLabel("", self)
        self._lbl_date.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        info_grid.addWidget(self._lbl_date, 1, 0)

        self._lbl_dim = QLabel("", self)
        self._lbl_dim.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 11px;")
        info_grid.addWidget(self._lbl_dim, 1, 1)

        # Row 2: GPS coordinates
        self._lbl_gps = QLabel("", self)
        self._lbl_gps.setStyleSheet(f"color: {Colors.EMERALD_LIGHT}; font-size: 11px; font-family: Consolas;")
        info_grid.addWidget(self._lbl_gps, 2, 0, 1, 2)

        # Row 3: Address Line
        self._lbl_addr = QLabel("", self)
        self._lbl_addr.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 10px;")
        self._lbl_addr.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._lbl_addr.setMaximumWidth(420)
        self._lbl_addr.setWordWrap(False)
        info_grid.addWidget(self._lbl_addr, 3, 0, 1, 2)

        meta_layout.addLayout(info_grid)
        layout.addLayout(meta_layout, stretch=1)

        # ── Action Buttons Column ─────────────────────────────────────────────
        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)

        self._btn_open = QPushButton("▶  Open Image", self)
        self._btn_open.setFixedWidth(110)
        self._btn_open.clicked.connect(self._on_open)
        btn_col.addWidget(self._btn_open)

        self._btn_locate = QPushButton("📁  In Explorer", self)
        self._btn_locate.setFixedWidth(110)
        self._btn_locate.clicked.connect(self._on_locate)
        btn_col.addWidget(self._btn_locate)

        self._btn_gmaps = QPushButton("🌐  Google Maps", self)
        self._btn_gmaps.setFixedWidth(110)
        self._btn_gmaps.clicked.connect(self._on_open_gmaps)
        btn_col.addWidget(self._btn_gmaps)

        layout.addLayout(btn_col)
        self.setVisible(False)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_item(self, item: Optional[PhotoItem]):
        self._item = item
        if item is None:
            self.setVisible(False)
            return

        self._thumb.set_pixmap(item.thumbnail)
        fm = QFontMetrics(self._lbl_name.font())
        elided_name = fm.elidedText(item.display_name, Qt.TextElideMode.ElideMiddle, 380)
        self._lbl_name.setText(elided_name)
        self._lbl_name.setToolTip(item.display_name)
        self._lbl_size.setText(item.formatted_size)

        # Type badge & Open button text
        if item.is_video:
            self._lbl_badge.setText(f"🎬 {item.video_format_str}")
            self._lbl_badge.setStyleSheet(
                f"background: #1e1b4b; color: {Colors.CYAN_LIGHT}; border: 1px solid {Colors.CYAN}; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: bold;"
            )
            self._btn_open.setText("▶  Open Video")
        elif item.is_pair:
            self._lbl_badge.setText("RAW + JPEG")
            self._lbl_badge.setStyleSheet(
                f"background: #1e0b36; color: {Colors.PURPLE_LIGHT}; border: 1px solid {Colors.PURPLE}; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: bold;"
            )
            self._btn_open.setText("▶  Open Image")
        elif item.raw_path:
            self._lbl_badge.setText(item.raw_path.suffix.upper().lstrip("."))
            self._lbl_badge.setStyleSheet(
                f"background: #1e0b36; color: {Colors.PURPLE_LIGHT}; border: 1px solid {Colors.PURPLE}; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: bold;"
            )
            self._btn_open.setText("▶  Open Image")
        else:
            self._lbl_badge.setText(item.display_path.suffix.upper().lstrip("."))
            self._lbl_badge.setStyleSheet(
                f"background: #082f49; color: {Colors.CYAN_LIGHT}; border: 1px solid {Colors.CYAN}; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: bold;"
            )
            self._btn_open.setText("▶  Open Image")

        # Camera & Exposure
        icon = "🎬" if item.is_video else "📷"
        self._lbl_camera.setText(f"{icon}  {item.camera_str}")
        self._lbl_exposure.setText(f"⚙️  {item.exposure_str}")

        # Date & Dimensions
        self._lbl_date.setText(f"📅  {item.date_str()}")
        dim_str = item.dimensions_str
        self._lbl_dim.setText(f"📐  {dim_str}" if dim_str else "")

        # GPS status & Address
        g = item.effective_gps
        if item.pending.strip_gps:
            self._lbl_gps.setText("🗑️ STAGED FOR REMOVAL (GPS will be deleted from file)")
            self._lbl_gps.setStyleSheet(f"color: {Colors.ROSE_LIGHT}; font-size: 11px; font-weight: bold;")
            self._lbl_addr.setText("Coordinates will be erased upon saving")
            self._btn_gmaps.setEnabled(False)
        elif item.pending.gps:
            gps = item.pending.gps
            self._lbl_gps.setText(f"⏳ STAGED: {gps[0]:.6f}, {gps[1]:.6f}")
            self._lbl_gps.setStyleSheet(f"color: {Colors.AMBER_LIGHT}; font-size: 11px; font-family: Consolas; font-weight: bold;")
            self._btn_gmaps.setEnabled(True)
            self._update_address(gps[0], gps[1])
        elif g:
            self._lbl_gps.setText(f"📍 GPS: {g[0]:.6f}, {g[1]:.6f}")
            self._lbl_gps.setStyleSheet(f"color: {Colors.EMERALD_LIGHT}; font-size: 11px; font-family: Consolas; font-weight: bold;")
            self._btn_gmaps.setEnabled(True)
            self._update_address(g[0], g[1])
        else:
            self._lbl_gps.setText("❌ No GPS metadata")
            self._lbl_gps.setStyleSheet(f"color: {Colors.ROSE_LIGHT}; font-size: 11px;")
            self._lbl_addr.setText("")
            self._btn_gmaps.setEnabled(False)

        self.setVisible(True)

    def _update_address(self, lat: float, lon: float):
        self._lbl_addr.setText("🏢 Resolving address…")
        # Async-like singleShot to prevent GUI blocking
        QTimer.singleShot(50, lambda: self._fetch_address(lat, lon))

    def _fetch_address(self, lat: float, lon: float):
        if self._item and self._item.effective_gps:
            g = self._item.effective_gps
            if abs(g[0] - lat) < 1e-4 and abs(g[1] - lon) < 1e-4:
                addr = reverse_geocode(lat, lon)
                if addr:
                    self._lbl_addr.setText(f"🏢 {addr}")
                    self._lbl_addr.setToolTip(addr)
                else:
                    self._lbl_addr.setText("")

    def refresh(self):
        self.set_item(self._item)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_open(self):
        if self._item:
            try:
                os.startfile(str(self._item.display_path))
            except Exception as exc:
                log.warning("startfile failed: %s", exc)
            self.open_requested.emit(self._item)

    def _on_locate(self):
        if self._item:
            self.locate_requested.emit(self._item)

    def _on_open_gmaps(self):
        if self._item and self._item.effective_gps:
            lat, lon = self._item.effective_gps
            url = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"
            webbrowser.open(url)
