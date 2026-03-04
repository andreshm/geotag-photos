"""photo_grid.py — Scrollable thumbnail grid with folder separators and GPS badges."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QRect, QTimer
from PySide6.QtGui import (
    QColor, QPainter, QPen, QFont, QFontMetrics, QBrush,
)
from PySide6.QtWidgets import (
    QWidget, QScrollArea, QVBoxLayout, QGridLayout,
    QFrame, QLabel, QApplication,
)

from .photo_item import PhotoItem

log = logging.getLogger(__name__)

CELL_W  = 180
CELL_H  = 215
THUMB_W = 160
THUMB_H = 160

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
# Folder section header
# ──────────────────────────────────────────────────────────────────────────────

class _FolderHeader(QLabel):
    """Horizontal separator showing a folder path above its group of photos."""

    def __init__(self, folder: Path, base_folder: Optional[Path], parent=None):
        # Show relative path when possible, else just the folder name
        try:
            rel = folder.relative_to(base_folder) if base_folder else folder
            text = str(rel) or folder.name
        except ValueError:
            text = str(folder)

        super().__init__(f"  📂  {text}", parent)
        self.setFixedHeight(24)
        self.setStyleSheet(
            "QLabel {"
            "  color: #475569; font-size: 10px; font-family: Consolas;"
            "  background: #111827; border-top: 1px solid #1e293b;"
            "  border-bottom: 1px solid #1e293b;"
            "  padding: 0 6px;"
            "}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Single photo cell
# ──────────────────────────────────────────────────────────────────────────────

class PhotoCell(QFrame):
    """One clickable, right-clickable photo thumbnail cell."""

    clicked          = Signal(object, bool, bool)   # item, ctrl, shift
    dbl_clicked      = Signal(object)
    clear_gps_req    = Signal(object)
    show_in_explorer = Signal(object)

    def __init__(self, item: PhotoItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setFixedSize(CELL_W, CELL_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(self._build_tooltip())
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    # ── painting ─────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        item    = self.item
        sel     = item.selected
        pending = item.pending.gps is not None

        painter.fillRect(self.rect(), QColor(CLR_CELL_SEL if sel else CLR_CELL_NORMAL))

        if sel:
            pen = QPen(QColor(CLR_BORDER_SEL), 2)
        elif pending:
            pen = QPen(QColor(CLR_BORDER_PEND), 2)
        else:
            pen = QPen(QColor("#2d3748"), 1)
        painter.setPen(pen)
        painter.drawRect(self.rect().adjusted(1, 1, -1, -1))

        # Thumbnail
        tr = QRect((CELL_W - THUMB_W) // 2, 8, THUMB_W, THUMB_H)
        if item.thumbnail:
            scaled = item.thumbnail.scaled(
                THUMB_W, THUMB_H,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(
                tr.x() + (THUMB_W - scaled.width()) // 2,
                tr.y() + (THUMB_H - scaled.height()) // 2,
                scaled,
            )
        else:
            painter.fillRect(tr, QColor("#2d3748"))
            painter.setPen(QColor("#4a5568"))
            painter.setFont(QFont("Segoe UI", 28))
            painter.drawText(tr, Qt.AlignmentFlag.AlignCenter, "📷")

        # GPS badge (top-right)
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

        # RAW badge (top-left)
        if item.is_pair:
            rb = QRect(4, 4, 32, 14)
            painter.setBrush(QBrush(QColor("#7c3aed")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rb, 3, 3)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
            painter.drawText(rb, Qt.AlignmentFlag.AlignCenter, "RAW+J")

        # Filename
        nr = QRect(4, THUMB_H + 12, CELL_W - 8, 18)
        painter.setPen(QColor(CLR_TEXT))
        painter.setFont(QFont("Segoe UI", 8))
        name = QFontMetrics(painter.font()).elidedText(
            item.display_name, Qt.TextElideMode.ElideMiddle, nr.width()
        )
        painter.drawText(nr, Qt.AlignmentFlag.AlignCenter, name)

        # Date
        dr = QRect(4, THUMB_H + 30, CELL_W - 8, 14)
        painter.setPen(QColor(CLR_TEXT_DIM))
        painter.setFont(QFont("Segoe UI", 7))
        painter.drawText(dr, Qt.AlignmentFlag.AlignCenter, item.date_str())

        # GPS line
        gr = QRect(4, THUMB_H + 44, CELL_W - 8, 14)
        if pending:
            painter.setPen(QColor(CLR_GPS_PEND))
        elif item.has_gps:
            painter.setPen(QColor(CLR_GPS_OK))
        else:
            painter.setPen(QColor(CLR_GPS_MISS))
        painter.setFont(QFont("Segoe UI", 7))
        painter.drawText(gr, Qt.AlignmentFlag.AlignCenter, item.gps_str())

        painter.end()

    # ── mouse ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            ctrl  = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.clicked.emit(self.item, ctrl, shift)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dbl_clicked.emit(self.item)

    def _show_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu   # local import keeps module fast
        item = self.item
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background:#2d3748; color:#e2e8f0; border:1px solid #4a5568; }
            QMenu::item:selected { background:#0f3460; }
            QMenu::separator { height:1px; background:#4a5568; margin:3px 0; }
        """)

        hdr = menu.addAction(f"📍  {item.gps_str()}")
        hdr.setEnabled(False)
        menu.addSeparator()

        act_clear = menu.addAction("✕  Clear pending GPS")
        act_clear.setEnabled(item.pending.gps is not None)
        act_clear.triggered.connect(lambda: self.clear_gps_req.emit(item))

        act_copy = menu.addAction("📋  Copy coordinates")
        g = item.effective_gps
        act_copy.setEnabled(g is not None)
        if g:
            act_copy.triggered.connect(
                lambda: QApplication.clipboard().setText(f"{g[0]:.8f}, {g[1]:.8f}")
            )

        menu.addSeparator()
        act_explorer = menu.addAction("📁  Show in Explorer")
        act_explorer.triggered.connect(lambda: self.show_in_explorer.emit(item))

        menu.exec(self.mapToGlobal(pos))

    def _build_tooltip(self) -> str:
        item  = self.item
        lines = [item.display_name]
        if item.is_pair:
            lines.append(f"RAW:  {item.raw_path.name}")    # type: ignore[union-attr]
        lines += [
            f"Date: {item.date_str()}",
            f"GPS:  {item.gps_str()}",
        ]
        if item.pending.gps:
            p = item.pending.gps
            lines.append(f"Pending: {p[0]:.6f}, {p[1]:.6f}")
        return "\n".join(lines)

    def refresh(self):
        self.setToolTip(self._build_tooltip())
        self.update()


# ──────────────────────────────────────────────────────────────────────────────
# Folder section  (header label + inner grid)
# ──────────────────────────────────────────────────────────────────────────────

class _FolderSection(QWidget):
    """One folder's worth of cells with a header label above them."""

    def __init__(self, folder: Path, base_folder: Optional[Path], parent=None):
        super().__init__(parent)
        self.folder  = folder
        self._cells: list[PhotoCell] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = _FolderHeader(folder, base_folder, self)
        outer.addWidget(self._header)

        self._grid_widget = QWidget(self)
        self._grid_widget.setStyleSheet(f"background: {CLR_BG};")
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setSpacing(6)
        self._grid.setContentsMargins(8, 6, 8, 6)
        outer.addWidget(self._grid_widget)

    def add_cell(self, cell: PhotoCell, cols: int):
        idx = len(self._cells)
        self._cells.append(cell)
        row, col = divmod(idx, cols)
        self._grid.addWidget(cell, row, col)

    def reflow(self, cols: int):
        for idx, cell in enumerate(self._cells):
            row, col = divmod(idx, cols)
            self._grid.addWidget(cell, row, col)

    def clear_cells(self):
        for cell in self._cells:
            self._grid.removeWidget(cell)
            cell.deleteLater()
        self._cells.clear()

    @property
    def cells(self) -> list[PhotoCell]:
        return self._cells


# ──────────────────────────────────────────────────────────────────────────────
# Main grid widget
# ──────────────────────────────────────────────────────────────────────────────

class PhotoGrid(QScrollArea):
    """Scrollable multi-select thumbnail grid with per-folder sections."""

    selection_changed = Signal(list)    # list[PhotoItem]
    photo_activated   = Signal(object)  # PhotoItem
    clear_gps_req     = Signal(object)  # PhotoItem
    show_in_explorer  = Signal(object)  # PhotoItem

    def __init__(self, parent=None):
        super().__init__(parent)

        self._items:     list[PhotoItem]               = []
        self._cells:     list[PhotoCell]               = []
        self._sections:  dict[Path, _FolderSection]   = {}
        self._base_folder: Optional[Path]              = None
        self._last_idx:  Optional[int]                 = None

        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.setInterval(80)
        self._reflow_timer.timeout.connect(self._reflow)

        self._container = QWidget()
        self._container.setStyleSheet(f"background: {CLR_BG};")
        self._outer_layout = QVBoxLayout(self._container)
        self._outer_layout.setContentsMargins(0, 0, 0, 8)
        self._outer_layout.setSpacing(0)
        self._outer_layout.addStretch()   # push sections to top

        self.setWidget(self._container)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(f"QScrollArea {{ background: {CLR_BG}; border: none; }}")

    # ── public API ────────────────────────────────────────────────────────────

    def set_base_folder(self, folder: Path):
        """Set the root folder for relative-path display in headers."""
        self._base_folder = folder

    def add_item(self, item: PhotoItem) -> PhotoCell:
        idx = len(self._items)
        self._items.append(item)

        cell = PhotoCell(item)
        cell.clicked.connect(self._on_cell_clicked)
        cell.dbl_clicked.connect(self.photo_activated)
        cell.clear_gps_req.connect(self.clear_gps_req)
        cell.show_in_explorer.connect(self.show_in_explorer)
        self._cells.append(cell)

        # Get or create section for this photo's folder
        folder = item.folder
        if folder not in self._sections:
            section = _FolderSection(folder, self._base_folder, self._container)
            self._sections[folder] = section
            # Insert before the trailing stretch
            self._outer_layout.insertWidget(
                self._outer_layout.count() - 1, section
            )

        cols = self._visible_columns()
        self._sections[folder].add_cell(cell, cols)

        self._reflow_timer.start()
        return cell

    def clear(self):
        self._reflow_timer.stop()
        for section in self._sections.values():
            section.clear_cells()
            self._outer_layout.removeWidget(section)
            section.deleteLater()
        self._sections.clear()
        self._cells.clear()
        self._items.clear()
        self._last_idx = None
        self._base_folder = None
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

        if shift and self._last_idx is not None:
            lo, hi = min(idx, self._last_idx), max(idx, self._last_idx)
            if not ctrl:
                for i in self._items:
                    i.selected = False
            for i in range(lo, hi + 1):
                self._items[i].selected = True
        elif ctrl:
            item.selected = not item.selected
            self._last_idx = idx
        else:
            for i in self._items:
                i.selected = False
            item.selected = True
            self._last_idx = idx

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
        for section in self._sections.values():
            section.reflow(cols)
