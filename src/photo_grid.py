"""photo_grid.py — scrollable thumbnail grid with GPS status indicators."""

from __future__ import annotations

import logging
import subprocess
from typing import Optional

from PySide6.QtCore import Qt, Signal, QRect, QTimer
from PySide6.QtGui import (
    QColor, QPainter, QPen, QFont, QFontMetrics, QBrush,
)
from PySide6.QtWidgets import (
    QWidget, QScrollArea, QGridLayout, QFrame,
    QMenu, QApplication,
)

from .photo_item import PhotoItem

log = logging.getLogger(__name__)

CELL_W  = 180
CELL_H  = 215   # thumb + labels
THUMB_W = 160
THUMB_H = 160

# ── palette ──────────────────────────────────────────────────────────────────
CLR_BG          = "#1a1a2e"
CLR_CELL_NORMAL = "#16213e"
CLR_CELL_SEL    = "#0f3460"
CLR_BORDER_SEL  = "#e94560"
CLR_BORDER_PEND = "#f59e0b"
CLR_GPS_OK      = "#22c55e"
CLR_GPS_MISS    = "#ef4444"
CLR_GPS_PEND    = "#f59e0b"
CLR_TEXT        = "#e2e8f0"
CLR_TEXT_DIM    = "#94a3b8"


# ──────────────────────────────────────────────────────────────────────────────
# Single photo cell
# ──────────────────────────────────────────────────────────────────────────────

class PhotoCell(QFrame):
    """One clickable, right-clickable photo thumbnail cell."""

    clicked         = Signal(object, bool, bool)  # item, ctrl, shift
    dbl_clicked     = Signal(object)
    clear_gps_req   = Signal(object)              # request to clear pending GPS
    show_in_explorer= Signal(object)              # request to reveal in Explorer

    def __init__(self, item: PhotoItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setFixedSize(CELL_W, CELL_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(self._build_tooltip())
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    # ── painting ─────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        item     = self.item
        selected = item.selected
        pending  = item.pending.gps is not None

        # Background
        painter.fillRect(self.rect(), QColor(CLR_CELL_SEL if selected else CLR_CELL_NORMAL))

        # Border
        if selected:
            pen = QPen(QColor(CLR_BORDER_SEL), 2)
        elif pending:
            pen = QPen(QColor(CLR_BORDER_PEND), 2)
        else:
            pen = QPen(QColor("#2d3748"), 1)
        painter.setPen(pen)
        painter.drawRect(self.rect().adjusted(1, 1, -1, -1))

        # Thumbnail
        thumb_rect = QRect((CELL_W - THUMB_W) // 2, 8, THUMB_W, THUMB_H)
        if item.thumbnail:
            scaled = item.thumbnail.scaled(
                THUMB_W, THUMB_H,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = thumb_rect.x() + (THUMB_W - scaled.width()) // 2
            y = thumb_rect.y() + (THUMB_H - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            painter.fillRect(thumb_rect, QColor("#2d3748"))
            painter.setPen(QColor("#4a5568"))
            painter.setFont(QFont("Segoe UI", 28))
            painter.drawText(thumb_rect, Qt.AlignmentFlag.AlignCenter, "📷")

        # ── GPS status badge (top-right) ─────────────────────────────────────
        badge = QRect(CELL_W - 22, 4, 18, 18)
        if pending:
            clr, icon = CLR_GPS_PEND, "●"
        elif item.has_gps:
            clr, icon = CLR_GPS_OK, "✓"
        else:
            clr, icon = CLR_GPS_MISS, "✕"

        painter.setBrush(QBrush(QColor(clr)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(badge)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, icon)

        # ── RAW badge (top-left) ─────────────────────────────────────────────
        if item.is_pair:
            raw_badge = QRect(4, 4, 28, 14)
            painter.setBrush(QBrush(QColor("#7c3aed")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(raw_badge, 3, 3)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
            painter.drawText(raw_badge, Qt.AlignmentFlag.AlignCenter, "RAW+J")

        # ── Filename ─────────────────────────────────────────────────────────
        name_rect = QRect(4, THUMB_H + 12, CELL_W - 8, 20)
        painter.setPen(QColor(CLR_TEXT))
        painter.setFont(QFont("Segoe UI", 8))
        name = QFontMetrics(painter.font()).elidedText(
            item.display_name, Qt.TextElideMode.ElideMiddle, name_rect.width()
        )
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignCenter, name)

        # ── Date ─────────────────────────────────────────────────────────────
        date_rect = QRect(4, THUMB_H + 30, CELL_W - 8, 16)
        painter.setPen(QColor(CLR_TEXT_DIM))
        painter.setFont(QFont("Segoe UI", 7))
        painter.drawText(date_rect, Qt.AlignmentFlag.AlignCenter, item.date_str())

        # ── GPS line ─────────────────────────────────────────────────────────
        gps_rect = QRect(4, THUMB_H + 46, CELL_W - 8, 14)
        if pending:
            painter.setPen(QColor(CLR_GPS_PEND))
        elif item.has_gps:
            painter.setPen(QColor(CLR_GPS_OK))
        else:
            painter.setPen(QColor(CLR_GPS_MISS))
        painter.setFont(QFont("Segoe UI", 7))
        painter.drawText(gps_rect, Qt.AlignmentFlag.AlignCenter, item.gps_str())

        painter.end()

    # ── mouse / context menu ──────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            ctrl  = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.clicked.emit(self.item, ctrl, shift)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dbl_clicked.emit(self.item)

    def _show_context_menu(self, pos):
        item = self.item
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background:#2d3748; color:#e2e8f0; border:1px solid #4a5568; }
            QMenu::item:selected { background:#0f3460; }
            QMenu::separator { height:1px; background:#4a5568; margin:3px 0; }
        """)

        # GPS info header (disabled, just informational)
        hdr = menu.addAction(f"📍  {item.gps_str()}")
        hdr.setEnabled(False)
        menu.addSeparator()

        # Clear pending GPS
        act_clear = menu.addAction("✕  Clear pending GPS")
        act_clear.setEnabled(item.pending.gps is not None)
        act_clear.triggered.connect(lambda: self.clear_gps_req.emit(item))

        # Copy GPS to clipboard
        act_copy = menu.addAction("📋  Copy coordinates")
        g = item.effective_gps
        act_copy.setEnabled(g is not None)
        if g:
            act_copy.triggered.connect(
                lambda: QApplication.clipboard().setText(f"{g[0]:.8f}, {g[1]:.8f}")
            )

        menu.addSeparator()

        # Show in Explorer
        act_explorer = menu.addAction("📁  Show in Explorer")
        act_explorer.triggered.connect(lambda: self.show_in_explorer.emit(item))

        menu.exec(self.mapToGlobal(pos))

    # ── tooltip ───────────────────────────────────────────────────────────────

    def _build_tooltip(self) -> str:
        item = self.item
        lines = [item.display_name]
        if item.is_pair:
            lines.append(f"RAW: {item.raw_path.name}")      # type: ignore[union-attr]
        lines.append(f"Date:  {item.date_str()}")
        lines.append(f"GPS:   {item.gps_str()}")
        if item.pending.gps:
            lines.append(f"Pending GPS: {item.pending.gps[0]:.6f}, {item.pending.gps[1]:.6f}")
        return "\n".join(lines)

    def refresh(self):
        self.setToolTip(self._build_tooltip())
        self.update()


# ──────────────────────────────────────────────────────────────────────────────
# Grid container
# ──────────────────────────────────────────────────────────────────────────────

class PhotoGrid(QScrollArea):
    """Scrollable, multi-select thumbnail grid."""

    selection_changed = Signal(list)    # list[PhotoItem]
    photo_activated   = Signal(object)  # PhotoItem — double-click
    clear_gps_req     = Signal(object)  # PhotoItem — context menu
    show_in_explorer  = Signal(object)  # PhotoItem — context menu

    def __init__(self, parent=None):
        super().__init__(parent)

        self._items:            list[PhotoItem] = []
        self._cells:            list[PhotoCell] = []
        self._last_clicked_idx: Optional[int]   = None

        # Throttle reflow + state updates during bulk adds
        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.setInterval(80)
        self._reflow_timer.timeout.connect(self._reflow)

        self._container = QWidget()
        self._container.setStyleSheet(f"background: {CLR_BG};")
        self._layout = QGridLayout(self._container)
        self._layout.setSpacing(6)
        self._layout.setContentsMargins(8, 8, 8, 8)

        self.setWidget(self._container)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            f"QScrollArea {{ background: {CLR_BG}; border: none; }}"
        )

    # ── public API ────────────────────────────────────────────────────────────

    def add_item(self, item: PhotoItem) -> PhotoCell:
        idx = len(self._items)
        self._items.append(item)

        cell = PhotoCell(item)
        cell.clicked.connect(self._on_cell_clicked)
        cell.dbl_clicked.connect(self.photo_activated)
        cell.clear_gps_req.connect(self.clear_gps_req)
        cell.show_in_explorer.connect(self.show_in_explorer)
        self._cells.append(cell)

        cols = self._visible_columns()
        row, col = divmod(idx, cols)
        self._layout.addWidget(cell, row, col)

        # Defer reflow in case many items are being added quickly
        self._reflow_timer.start()
        return cell

    def clear(self):
        self._reflow_timer.stop()
        for cell in self._cells:
            self._layout.removeWidget(cell)
            cell.deleteLater()
        self._cells.clear()
        self._items.clear()
        self._last_clicked_idx = None
        self.selection_changed.emit([])

    def refresh_cell(self, item: PhotoItem):
        for cell in self._cells:
            if cell.item is item:
                cell.refresh()
                return

    def refresh_all(self):
        for cell in self._cells:
            cell.refresh()

    def selected_items(self) -> list[PhotoItem]:
        return [i for i in self._items if i.selected]

    def select_all(self):
        for i in self._items:
            i.selected = True
        self.refresh_all()
        self.selection_changed.emit(self.selected_items())

    def deselect_all(self):
        for i in self._items:
            i.selected = False
        self.refresh_all()
        self.selection_changed.emit([])

    def select_missing_gps(self):
        for i in self._items:
            i.selected = not i.has_gps and not i.has_pending_gps
        self.refresh_all()
        self.selection_changed.emit(self.selected_items())

    @property
    def items(self) -> list[PhotoItem]:
        return self._items

    # ── selection ─────────────────────────────────────────────────────────────

    def _on_cell_clicked(self, item: PhotoItem, ctrl: bool, shift: bool):
        idx = self._items.index(item)

        if shift and self._last_clicked_idx is not None:
            lo = min(idx, self._last_clicked_idx)
            hi = max(idx, self._last_clicked_idx)
            if not ctrl:
                for i in self._items:
                    i.selected = False
            for i in range(lo, hi + 1):
                self._items[i].selected = True
        elif ctrl:
            item.selected = not item.selected
            self._last_clicked_idx = idx
        else:
            for i in self._items:
                i.selected = False
            item.selected = True
            self._last_clicked_idx = idx

        self.refresh_all()
        self.selection_changed.emit(self.selected_items())

    # ── layout ────────────────────────────────────────────────────────────────

    def _visible_columns(self) -> int:
        w = self.viewport().width() if self.viewport() else self.width()
        return max(1, w // (CELL_W + 6))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_timer.start()

    def _reflow(self):
        cols = self._visible_columns()
        for idx, cell in enumerate(self._cells):
            row, col = divmod(idx, cols)
            self._layout.addWidget(cell, row, col)
