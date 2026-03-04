"""photo_preview.py — Compact info bar shown below the map when a photo is selected."""

from __future__ import annotations

import os
import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPixmap, QColor, QPainter, QFont, QPen
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QFrame, QSizePolicy,
)

from .photo_item import PhotoItem

log = logging.getLogger(__name__)

PREVIEW_H = 130    # fixed height of the bar


class _ThumbFrame(QWidget):
    """Draws the thumbnail with a subtle border, sized to PREVIEW_H."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self.setFixedSize(PREVIEW_H - 10, PREVIEW_H - 10)

    def set_pixmap(self, px: Optional[QPixmap]):
        self._pixmap = px
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()

        painter.fillRect(r, QColor("#0d1117"))
        painter.setPen(QPen(QColor("#2d3748"), 1))
        painter.drawRect(r.adjusted(0, 0, -1, -1))

        if self._pixmap:
            scaled = self._pixmap.scaled(
                r.width() - 4, r.height() - 4,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = r.x() + (r.width()  - scaled.width())  // 2
            y = r.y() + (r.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            painter.setPen(QColor("#4a5568"))
            painter.setFont(QFont("Segoe UI", 20))
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, "📷")

        painter.end()


class PhotoInfoBar(QFrame):
    """A slim horizontal panel showing the selected photo's info.

    Signals
    -------
    open_requested  — user clicked "Open" button (open with default app)
    locate_requested — user clicked "Locate" button (reveal in Explorer)
    """

    open_requested    = Signal(object)   # PhotoItem
    locate_requested  = Signal(object)   # PhotoItem

    def __init__(self, parent=None):
        super().__init__(parent)
        self._item: Optional[PhotoItem] = None

        self.setFixedHeight(PREVIEW_H)
        self.setStyleSheet(
            "PhotoInfoBar { background: #0d1117; border-top: 1px solid #2d3748; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(12)

        # ── Thumbnail ─────────────────────────────────────────────────────────
        self._thumb = _ThumbFrame(self)
        layout.addWidget(self._thumb)

        # ── Info block ────────────────────────────────────────────────────────
        info = QVBoxLayout()
        info.setSpacing(2)

        self._lbl_name = QLabel("", self)
        self._lbl_name.setStyleSheet(
            "color:#e2e8f0; font-size:13px; font-weight:bold;"
        )
        self._lbl_name.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        info.addWidget(self._lbl_name)

        self._lbl_type = QLabel("", self)
        self._lbl_type.setStyleSheet("color:#7c3aed; font-size:11px;")
        info.addWidget(self._lbl_type)

        self._lbl_date = QLabel("", self)
        self._lbl_date.setStyleSheet("color:#94a3b8; font-size:11px;")
        info.addWidget(self._lbl_date)

        self._lbl_gps = QLabel("", self)
        self._lbl_gps.setStyleSheet("color:#f59e0b; font-size:11px;")
        info.addWidget(self._lbl_gps)

        self._lbl_folder = QLabel("", self)
        self._lbl_folder.setStyleSheet("color:#4a5568; font-size:10px;")
        self._lbl_folder.setWordWrap(False)
        info.addWidget(self._lbl_folder)

        info.addStretch()
        layout.addLayout(info, stretch=1)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)

        self._btn_open = QPushButton("▶  Open", self)
        self._btn_open.setToolTip("Open with default application")
        self._btn_open.setFixedWidth(90)
        self._btn_open.setStyleSheet(
            "QPushButton { background:#1e3a5f; color:#93c5fd; border:1px solid #1e40af;"
            " border-radius:4px; padding:5px; font-size:11px; }"
            "QPushButton:hover { background:#1e40af; }"
        )
        self._btn_open.clicked.connect(self._on_open)
        btn_col.addWidget(self._btn_open)

        self._btn_locate = QPushButton("📁  Locate", self)
        self._btn_locate.setToolTip("Show in Windows Explorer")
        self._btn_locate.setFixedWidth(90)
        self._btn_locate.setStyleSheet(
            "QPushButton { background:#1c3325; color:#6ee7b7; border:1px solid #065f46;"
            " border-radius:4px; padding:5px; font-size:11px; }"
            "QPushButton:hover { background:#065f46; }"
        )
        self._btn_locate.clicked.connect(self._on_locate)
        btn_col.addWidget(self._btn_locate)

        btn_col.addStretch()
        layout.addLayout(btn_col)

        # Start hidden — shown when a photo is selected
        self.setVisible(False)

    # ── public API ────────────────────────────────────────────────────────────

    def set_item(self, item: Optional[PhotoItem]):
        """Update the bar for *item*. Pass None to hide."""
        self._item = item

        if item is None:
            self.setVisible(False)
            return

        # Thumbnail
        self._thumb.set_pixmap(item.thumbnail)

        # Name
        self._lbl_name.setText(item.display_name)

        # Type badge
        if item.is_pair:
            self._lbl_type.setText(
                f"RAW+JPEG  ·  {item.raw_path.suffix.upper()[1:]} + "   # type: ignore[union-attr]
                f"{item.jpeg_path.suffix.upper()[1:]}"                   # type: ignore[union-attr]
            )
        elif item.raw_path:
            self._lbl_type.setText(f"RAW  ·  {item.raw_path.suffix.upper()[1:]}")
        elif item.jpeg_path:
            self._lbl_type.setText(f"JPEG")
        else:
            self._lbl_type.setText(item.display_path.suffix.upper()[1:])

        # Date
        self._lbl_date.setText(f"📅  {item.date_str()}")

        # GPS
        g = item.effective_gps
        if item.pending.gps:
            gps = item.pending.gps
            self._lbl_gps.setText(f"⏳  {gps[0]:.6f},  {gps[1]:.6f}  (pending — not saved)")
            self._lbl_gps.setStyleSheet("color:#f59e0b; font-size:11px;")
        elif g:
            self._lbl_gps.setText(f"📍  {g[0]:.6f},  {g[1]:.6f}")
            self._lbl_gps.setStyleSheet("color:#22c55e; font-size:11px;")
        else:
            self._lbl_gps.setText("❌  No GPS data")
            self._lbl_gps.setStyleSheet("color:#ef4444; font-size:11px;")

        # Folder (relative if possible)
        folder = str(item.folder)
        self._lbl_folder.setText(f"📂  {folder}")
        self._lbl_folder.setToolTip(folder)

        self.setVisible(True)

    def refresh(self):
        """Refresh labels for the current item (e.g. after thumbnail loads)."""
        self.set_item(self._item)

    # ── private ───────────────────────────────────────────────────────────────

    def _on_open(self):
        if self._item:
            try:
                os.startfile(str(self._item.display_path))   # Windows only
            except Exception as exc:
                log.warning("startfile failed: %s", exc)
            self.open_requested.emit(self._item)

    def _on_locate(self):
        if self._item:
            self.locate_requested.emit(self._item)
