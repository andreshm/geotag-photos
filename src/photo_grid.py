"""photo_grid.py — High-performance multi-select thumbnail grid with pre-cached pixmaps, filter chips, and video overlays."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QRect, QTimer, QSize
from PySide6.QtGui import (
    QColor, QPainter, QPen, QFont, QFontMetrics, QBrush, QKeyEvent, QPixmap, QAction
)
from PySide6.QtWidgets import (
    QWidget, QScrollArea, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFrame, QLabel, QApplication, QPushButton, QComboBox,
    QSlider, QLineEdit, QMenu
)

from resources.theme import Colors, STYLE_MODERN_CYBER
from .photo_item import PhotoItem

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Multi-Select Checkable Filter Menu
# ─────────────────────────────────────────────────────────────────────────────

class _CheckableMenu(QMenu):
    """Custom popup menu that keeps open when toggling checkable items for seamless multi-selection."""

    def mouseReleaseEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        action = self.actionAt(pos)
        if action and action.isCheckable():
            action.trigger()
            event.accept()
            return
        super().mouseReleaseEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# Folder Section Header
# ─────────────────────────────────────────────────────────────────────────────

class _FolderHeader(QFrame):
    """Sleek folder separator bar."""

    def __init__(self, folder: Path, base_folder: Optional[Path], count: int = 0, parent=None):
        super().__init__(parent)
        self.folder = folder
        self.setFixedHeight(28)
        self.setStyleSheet(
            f"QFrame {{ background: #0b1222; border-top: 1px solid {Colors.BORDER_DEFAULT};"
            f" border-bottom: 1px solid {Colors.BORDER_DEFAULT}; }}"
        )

        try:
            rel = folder.relative_to(base_folder) if base_folder else folder
            text = str(rel) or folder.name
        except ValueError:
            text = str(folder)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(6)

        icon_lbl = QLabel("📂", self)
        lay.addWidget(icon_lbl)

        self.name_lbl = QLabel(text, self)
        self.name_lbl.setStyleSheet(f"color: {Colors.CYAN_LIGHT}; font-size: 11px; font-weight: 600; font-family: Consolas;")
        lay.addWidget(self.name_lbl, stretch=1)

        self.count_lbl = QLabel(f"{count} items", self)
        self.count_lbl.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 10px;")
        lay.addWidget(self.count_lbl)

    def set_count(self, count: int):
        self.count_lbl.setText(f"{count} items")


# ─────────────────────────────────────────────────────────────────────────────
# Modern Photo & Video Card Cell (High Performance Cached Painting)
# ─────────────────────────────────────────────────────────────────────────────

# Module-level static fonts to avoid per-frame font object instantiation
_FONT_TITLE = QFont("Segoe UI", 8)
_FONT_TITLE_BOLD = QFont("Segoe UI", 8, QFont.Weight.Bold)
_FONT_SUB = QFont("Segoe UI", 7)
_FONT_FOLDER = QFont("Segoe UI", 6)
_FONT_BADGE = QFont("Segoe UI", 8, QFont.Weight.Bold)
_FONT_TYPE_BADGE = QFont("Segoe UI", 6, QFont.Weight.Bold)
_FONT_PLAY = QFont("Segoe UI", 10, QFont.Weight.Bold)
_FONT_DUR = QFont("Segoe UI", 7, QFont.Weight.Bold)
_FONT_PLACEHOLDER = QFont("Segoe UI", 24)


class PhotoCell(QFrame):
    """Interactive card cell with cached pixmaps, video badges, pre-cached text, and zero-allocation paintEvent."""

    clicked          = Signal(object, bool, bool)   # item, ctrl, shift
    dbl_clicked      = Signal(object)
    clear_gps_req    = Signal(object)
    strip_gps_req    = Signal(object)
    show_in_explorer = Signal(object)

    def __init__(self, item: PhotoItem, card_w: int = 180, card_h: int = 215, parent=None):
        super().__init__(parent)
        self.item = item
        self.card_w = card_w
        self.card_h = card_h
        self.is_filtered_visible: bool = True
        self.show_folder_badge: bool = False
        self._cached_pixmap: Optional[QPixmap] = None
        self._cached_pixmap_pos: tuple[int, int] = (0, 0)
        self._cached_name: str = ""
        self._cached_sub: str = ""
        self._cached_folder: str = ""

        self.setFixedSize(self.card_w, self.card_h)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(self._build_tooltip())
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self._update_scaled_pixmap()
        self._update_cached_text()

    def _update_scaled_pixmap(self):
        """Pre-scale pixmap once on size change or thumbnail arrival so paintEvent never allocates."""
        if not self.item.thumbnail:
            self._cached_pixmap = None
            return

        thumb_w = self.card_w - 20
        thumb_h = self.card_h - 60
        try:
            self._cached_pixmap = self.item.thumbnail.scaled(
                thumb_w, thumb_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = 10 + (thumb_w - self._cached_pixmap.width()) // 2
            y = 8 + (thumb_h - self._cached_pixmap.height()) // 2
            self._cached_pixmap_pos = (x, y)
        except Exception:
            self._cached_pixmap = None

    def _update_cached_text(self):
        """Pre-calculate and elide text labels so paintEvent performs 0 typography calculations."""
        item = self.item
        avail_w = self.card_w - 12

        fm_t = QFontMetrics(_FONT_TITLE)
        self._cached_name = fm_t.elidedText(item.display_name, Qt.TextElideMode.ElideMiddle, avail_w)

        if item.pending.strip_gps:
            sub_text = "🗑️ Strip GPS"
        elif item.pending.gps:
            sub_text = "⏳ " + item.gps_str()
        elif item.has_gps:
            sub_text = "📍 " + item.gps_str()
        else:
            sub_text = item.date_str()

        fm_s = QFontMetrics(_FONT_SUB)
        self._cached_sub = fm_s.elidedText(sub_text, Qt.TextElideMode.ElideMiddle, avail_w)

        if item.folder:
            fm_f = QFontMetrics(_FONT_FOLDER)
            self._cached_folder = fm_f.elidedText(f"📁 {item.folder.name}", Qt.TextElideMode.ElideMiddle, avail_w - 6)
        else:
            self._cached_folder = ""

    def update_size(self, card_w: int, card_h: int):
        self.card_w = card_w
        self.card_h = card_h
        self.setFixedSize(self.card_w, self.card_h)
        self._update_scaled_pixmap()
        self._update_cached_text()
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        item = self.item
        sel = item.selected
        pending = item.pending.gps is not None or item.pending.strip_gps

        # Card Background
        bg_color = QColor("#082f49" if sel else (Colors.BG_CARD if not pending else "#1c1404"))
        painter.setBrush(QBrush(bg_color))

        # Border
        if sel:
            painter.setPen(QPen(QColor(Colors.CYAN), 2))
        elif pending:
            painter.setPen(QPen(QColor(Colors.AMBER), 2))
        else:
            painter.setPen(QPen(QColor(Colors.BORDER_CARD), 1))

        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)

        # Thumbnail Area
        thumb_w = self.card_w - 20
        thumb_h = self.card_h - 60
        tr = QRect(10, 8, thumb_w, thumb_h)

        if self._cached_pixmap:
            painter.drawPixmap(self._cached_pixmap_pos[0], self._cached_pixmap_pos[1], self._cached_pixmap)
        else:
            painter.setBrush(QBrush(QColor("#0b1222")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(tr, 4, 4)
            painter.setPen(QColor(Colors.TEXT_MUTED))
            painter.setFont(_FONT_PLACEHOLDER)
            icon = "🎬" if item.is_video else "📷"
            painter.drawText(tr, Qt.AlignmentFlag.AlignCenter, icon)

        # Play Icon Overlay for Videos
        if item.is_video:
            play_size = 28
            play_rect = QRect(
                tr.center().x() - play_size // 2,
                tr.center().y() - play_size // 2,
                play_size, play_size
            )
            painter.setBrush(QBrush(QColor(0, 0, 0, 150)))
            painter.setPen(QPen(QColor(Colors.CYAN), 1.5))
            painter.drawEllipse(play_rect)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(_FONT_PLAY)
            painter.drawText(play_rect, Qt.AlignmentFlag.AlignCenter, "▶")

        # Bottom-Right Duration Pill for Videos
        if item.is_video and item.duration_str:
            pill_w = 44
            pill_h = 16
            pill_rect = QRect(tr.right() - pill_w - 4, tr.bottom() - pill_h - 4, pill_w, pill_h)
            painter.setBrush(QBrush(QColor(0, 0, 0, 180)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(pill_rect, 4, 4)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(_FONT_DUR)
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, item.duration_str)

        # Top-Right GPS Status Badge
        badge_rect = QRect(self.card_w - 24, 6, 18, 18)
        if item.pending.strip_gps:
            clr, icon = Colors.ROSE, "🗑️"
        elif item.pending.gps:
            clr, icon = Colors.AMBER, "●"
        elif item.has_gps:
            clr, icon = Colors.EMERALD, "✓"
        else:
            clr, icon = Colors.ROSE, "✕"

        painter.setBrush(QBrush(QColor(clr)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(badge_rect)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(_FONT_BADGE)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, icon)

        # Top-Left Format Mismatch Badge / Video Badge / RAW Badge
        if item.format_mismatch:
            true_fmt = item.format_mismatch[0].lstrip(".").upper()
            rb = QRect(6, 6, 48, 14)
            painter.setBrush(QBrush(QColor("#78350f")))
            painter.setPen(QPen(QColor(Colors.AMBER), 1))
            painter.drawRoundedRect(rb, 3, 3)
            painter.setPen(QColor(Colors.AMBER_LIGHT))
            painter.setFont(_FONT_TYPE_BADGE)
            painter.drawText(rb, Qt.AlignmentFlag.AlignCenter, f"⚠️ {true_fmt}")
        elif item.is_video:
            rb = QRect(6, 6, 46, 14)
            painter.setBrush(QBrush(QColor(Colors.BLUE_BG)))
            painter.setPen(QPen(QColor(Colors.CYAN), 1))
            painter.drawRoundedRect(rb, 3, 3)
            painter.setPen(QColor(Colors.CYAN_LIGHT))
            painter.setFont(_FONT_TYPE_BADGE)
            painter.drawText(rb, Qt.AlignmentFlag.AlignCenter, f"🎬 {item.video_format_str}")
        elif item.is_pair:
            rb = QRect(6, 6, 38, 14)
            painter.setBrush(QBrush(QColor(Colors.PURPLE)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rb, 3, 3)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(_FONT_SUB)
            painter.drawText(rb, Qt.AlignmentFlag.AlignCenter, "RAW+J")
        elif item.raw_path:
            rb = QRect(6, 6, 30, 14)
            painter.setBrush(QBrush(QColor(Colors.PURPLE_BG)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rb, 3, 3)
            painter.setPen(QColor(Colors.PURPLE_LIGHT))
            painter.setFont(_FONT_SUB)
            painter.drawText(rb, Qt.AlignmentFlag.AlignCenter, "RAW")

        # Filename
        nr = QRect(6, thumb_h + 12, self.card_w - 12, 16)
        painter.setPen(QColor(Colors.TEXT_PRIMARY))
        painter.setFont(_FONT_TITLE_BOLD if sel else _FONT_TITLE)
        painter.drawText(nr, Qt.AlignmentFlag.AlignCenter, self._cached_name)

        # In Flat View mode: Folder badge tag over thumbnail bottom
        if self.show_folder_badge and self._cached_folder:
            fr = QRect(8, thumb_h - 12, self.card_w - 16, 13)
            painter.setBrush(QBrush(QColor(10, 15, 25, 220)))
            painter.setPen(QPen(QColor(Colors.BORDER_DEFAULT), 1))
            painter.drawRoundedRect(fr, 3, 3)
            painter.setPen(QColor(Colors.CYAN_LIGHT))
            painter.setFont(_FONT_FOLDER)
            painter.drawText(fr, Qt.AlignmentFlag.AlignCenter, self._cached_folder)

        # Date / GPS Info Subtitle
        dr = QRect(6, thumb_h + 28, self.card_w - 12, 14)
        if item.pending.strip_gps:
            painter.setPen(QColor(Colors.ROSE_LIGHT))
        elif item.pending.gps:
            painter.setPen(QColor(Colors.AMBER))
        elif item.has_gps:
            painter.setPen(QColor(Colors.EMERALD))
        else:
            painter.setPen(QColor(Colors.TEXT_MUTED))

        painter.setFont(_FONT_SUB)
        painter.drawText(dr, Qt.AlignmentFlag.AlignCenter, self._cached_sub)

        painter.end()

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
        menu.setStyleSheet(STYLE_MODERN_CYBER)

        hdr = menu.addAction(f"📍  {item.gps_str()}")
        hdr.setEnabled(False)
        menu.addSeparator()

        act_clear = menu.addAction("✕  Clear staged GPS")
        act_clear.setEnabled(item.pending.gps is not None or item.pending.strip_gps)
        act_clear.triggered.connect(lambda: self.clear_gps_req.emit(item))

        act_strip = menu.addAction("🗑️  Delete GPS from file (Strip tag)")
        act_strip.setEnabled(item.has_gps or item.pending.gps is not None)
        act_strip.triggered.connect(lambda: self.strip_gps_req.emit(item))

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
        lines = [f"Name: {item.display_name}"]
        if item.is_video:
            lines.append(f"Type: {item.video_format_str} Video")
            if item.duration_str:
                lines.append(f"Duration: {item.duration_str}")
        if item.format_mismatch:
            lines.append(f"⚠️ Format Mismatch: True {item.format_mismatch[0].upper()} (disguised as {item.format_mismatch[1]})")
        if item.is_pair:
            lines.append(f"Pair: {item.raw_path.name}")
        lines.append(f"Date: {item.date_str()}")
        lines.append(f"GPS:  {item.gps_str()}")
        if item.camera_model:
            lines.append(f"Camera: {item.camera_str}")
        if item.pending.strip_gps:
            lines.append("🗑️ Staged: STRIP / DELETE GPS FROM FILE")
        elif item.pending.gps:
            lines.append(f"⏳ Staged: {item.pending.gps[0]:.6f}, {item.pending.gps[1]:.6f}")
        return "\n".join(lines)

    def refresh(self):
        self._update_scaled_pixmap()
        self._update_cached_text()
        self.setToolTip(self._build_tooltip())
        self.update()


# ─────────────────────────────────────────────────────────────────────────────
# Folder Section
# ─────────────────────────────────────────────────────────────────────────────

class _FolderSection(QWidget):
    """Section container grouping photos by folder."""

    def __init__(self, folder: Path, base_folder: Optional[Path], parent=None):
        super().__init__(parent)
        self.folder = folder
        self._cells: list[PhotoCell] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = _FolderHeader(folder, base_folder, 0, self)
        outer.addWidget(self._header)

        self._grid_widget = QWidget(self)
        self._grid_widget.setStyleSheet(f"background: {Colors.BG_CANVAS};")
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setSpacing(8)
        self._grid.setContentsMargins(10, 8, 10, 8)
        outer.addWidget(self._grid_widget)

    def add_cell(self, cell: PhotoCell, cols: int):
        idx = len(self._cells)
        self._cells.append(cell)
        row, col = divmod(idx, cols)
        self._grid.addWidget(cell, row, col)
        self._header.set_count(len(self._cells))

    def reflow(self, cols: int):
        if not self._cells:
            return
        self.setUpdatesEnabled(False)
        try:
            # Clear existing layout references safely to prevent overlapping pointer leaks
            while self._grid.count():
                self._grid.takeAt(0)

            vis_cells = [c for c in self._cells if c.is_filtered_visible]
            for idx, cell in enumerate(vis_cells):
                row, col = divmod(idx, cols)
                self._grid.addWidget(cell, row, col)
        finally:
            self.setUpdatesEnabled(True)

    def clear_cells(self):
        while self._grid.count():
            self._grid.takeAt(0)
        for cell in self._cells:
            cell.deleteLater()
        self._cells.clear()
        self._header.set_count(0)

    @property
    def cells(self) -> list[PhotoCell]:
        return self._cells


# ─────────────────────────────────────────────────────────────────────────────
# Main Photo Grid Widget (with Toolbar, Filters, and Zoom)
# ─────────────────────────────────────────────────────────────────────────────

class PhotoGrid(QWidget):
    """Modern scrollable photo explorer with interactive filter chips, sorting, and keyboard navigation."""

    selection_changed = Signal(list)    # list[PhotoItem]
    photo_activated   = Signal(object)  # PhotoItem
    clear_gps_req     = Signal(object)
    strip_gps_req     = Signal(object)
    show_in_explorer  = Signal(object)
    status_message    = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._all_items:     list[PhotoItem]             = []
        self._cells:         list[PhotoCell]             = []
        self._item_to_cell:  dict[PhotoItem, PhotoCell]  = {}
        self._sections:      dict[Path, _FolderSection] = {}
        self._base_folder:   Optional[Path]            = None
        self._last_idx:      Optional[int]               = None
        self._last_cols:     int                         = -1
        self._group_by_folder: bool                      = False
        self._last_group_mode: Optional[bool]            = None

        self._card_w = 180
        self._card_h = 215
        self._active_filters: set[str] = set()
        self._search_query = ""

        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.setInterval(180)
        self._reflow_timer.timeout.connect(self._reflow)

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar: Filter Dropdown, Jump, View & Sort ──────────────────────
        tb = QFrame(self)
        tb.setStyleSheet(
            f"background: {Colors.BG_PANEL}; border-bottom: 1px solid {Colors.BORDER_DEFAULT};"
        )
        tb.setFixedHeight(38)
        tb_lay = QHBoxLayout(tb)
        tb_lay.setContentsMargins(10, 4, 10, 4)
        tb_lay.setSpacing(6)

        # ── Multi-Select Filter Dropdown ──
        self._btn_filter = QPushButton("🎯 Filter: All ▾", tb)
        self._btn_filter.setObjectName("btn_filter_dropdown")
        self._btn_filter.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_filter.setToolTip("Filter media by GPS status or media type (multi-select supported)")
        self._btn_filter.setStyleSheet(f"""
            QPushButton#btn_filter_dropdown {{
                background: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 6px;
                color: {Colors.TEXT_PRIMARY};
                font-size: 11px;
                font-weight: 500;
                padding: 4px 10px 4px 10px;
                min-height: 22px;
            }}
            QPushButton#btn_filter_dropdown:hover {{
                background: {Colors.BG_CARD_HOVER};
                border-color: {Colors.CYAN};
                color: {Colors.CYAN_LIGHT};
            }}
            QPushButton#btn_filter_dropdown::menu-indicator {{
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 0px;
            }}
        """)

        self._filter_menu = _CheckableMenu(self)
        self._filter_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {Colors.BG_PANEL};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 8px;
                padding: 6px 4px;
                color: {Colors.TEXT_PRIMARY};
                font-size: 11px;
            }}
            QMenu::item {{
                padding: 5px 22px 5px 22px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {Colors.BG_CARD_HOVER};
                color: {Colors.CYAN_LIGHT};
            }}
            QMenu::item:checked {{
                font-weight: bold;
                color: {Colors.CYAN_LIGHT};
            }}
            QMenu::separator {{
                height: 1px;
                background: {Colors.BORDER_DEFAULT};
                margin: 4px 6px;
            }}
        """)

        # Action: Show All
        self._act_all = QAction("Show All Media", self)
        self._act_all.setCheckable(True)
        self._act_all.setChecked(True)
        self._act_all.triggered.connect(self._on_filter_all_triggered)
        self._filter_menu.addAction(self._act_all)

        self._filter_menu.addSeparator()

        # GPS status filters
        self._filter_actions: dict[str, QAction] = {}

        act_missing = QAction("🔴 Missing GPS", self)
        act_missing.setCheckable(True)
        act_missing.triggered.connect(lambda: self._on_filter_item_triggered("missing"))
        self._filter_menu.addAction(act_missing)
        self._filter_actions["missing"] = act_missing

        act_staged = QAction("⏳ Staged Changes", self)
        act_staged.setCheckable(True)
        act_staged.triggered.connect(lambda: self._on_filter_item_triggered("staged"))
        self._filter_menu.addAction(act_staged)
        self._filter_actions["staged"] = act_staged

        act_tagged = QAction("✓ Geotagged", self)
        act_tagged.setCheckable(True)
        act_tagged.triggered.connect(lambda: self._on_filter_item_triggered("tagged"))
        self._filter_menu.addAction(act_tagged)
        self._filter_actions["tagged"] = act_tagged

        self._filter_menu.addSeparator()

        # Media type filters
        act_vids = QAction("🎬 Videos Only", self)
        act_vids.setCheckable(True)
        act_vids.triggered.connect(lambda: self._on_filter_item_triggered("videos"))
        self._filter_menu.addAction(act_vids)
        self._filter_actions["videos"] = act_vids

        act_raw = QAction("📦 RAW Pairs Only", self)
        act_raw.setCheckable(True)
        act_raw.triggered.connect(lambda: self._on_filter_item_triggered("raw"))
        self._filter_menu.addAction(act_raw)
        self._filter_actions["raw"] = act_raw

        self._filter_menu.addSeparator()

        act_reset = QAction("↺ Reset Filters", self)
        act_reset.triggered.connect(self.reset_filters)
        self._filter_menu.addAction(act_reset)

        self._btn_filter.setMenu(self._filter_menu)
        tb_lay.addWidget(self._btn_filter)

        # ── Jump Untagged Navigation Buttons ──
        jump_box = QFrame(tb)
        jump_box.setStyleSheet(f"background: #1c0a10; border: 1px solid {Colors.ROSE_BG}; border-radius: 6px;")
        jl = QHBoxLayout(jump_box)
        jl.setContentsMargins(4, 1, 6, 1)
        jl.setSpacing(3)

        lbl_j_icon = QLabel("🔴", jump_box)
        lbl_j_icon.setStyleSheet("font-size: 10px;")
        jl.addWidget(lbl_j_icon)

        self._btn_prev_untagged = QPushButton("▲", jump_box)
        self._btn_prev_untagged.setToolTip("Jump to Previous Untagged Photo/Video (Shift+F3 or Alt+Up)")
        self._btn_prev_untagged.setFixedSize(24, 22)
        self._btn_prev_untagged.setStyleSheet("padding:0px; font-weight:bold; font-size:10px;")
        self._btn_prev_untagged.clicked.connect(self.jump_prev_untagged)
        jl.addWidget(self._btn_prev_untagged)

        self._btn_next_untagged = QPushButton("▼", jump_box)
        self._btn_next_untagged.setToolTip("Jump to Next Untagged Photo/Video (F3 or Alt+Down)")
        self._btn_next_untagged.setFixedSize(24, 22)
        self._btn_next_untagged.setStyleSheet("padding:0px; font-weight:bold; font-size:10px;")
        self._btn_next_untagged.clicked.connect(self.jump_next_untagged)
        jl.addWidget(self._btn_next_untagged)

        self._lbl_untagged_count = QLabel("", jump_box)
        self._lbl_untagged_count.setStyleSheet(f"color: {Colors.ROSE_LIGHT}; font-size: 10px; font-weight: bold;")
        jl.addWidget(self._lbl_untagged_count)

        tb_lay.addWidget(jump_box)

        tb_lay.addStretch()

        # Group by Folder Toggle
        self._btn_group_folder = QPushButton("🌐 Flat View", tb)
        self._btn_group_folder.setCheckable(True)
        self._btn_group_folder.setChecked(False)
        self._btn_group_folder.setToolTip("Toggle Flat Global View vs Grouped by Folder View")
        self._btn_group_folder.clicked.connect(self._on_group_toggle_clicked)
        tb_lay.addWidget(self._btn_group_folder)

        # Sort Dropdown
        lbl_sort = QLabel("Sort:", tb)
        lbl_sort.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 11px;")
        tb_lay.addWidget(lbl_sort)

        self._combo_sort = QComboBox(tb)
        self._combo_sort.addItems(["Date Taken", "Filename", "GPS Status", "File Size"])
        self._combo_sort.currentIndexChanged.connect(self._on_sort_changed)
        self._combo_sort.setFixedWidth(110)
        tb_lay.addWidget(self._combo_sort)

        # Zoom Slider
        lbl_zoom = QLabel("🔍", tb)
        tb_lay.addWidget(lbl_zoom)

        self._slider_zoom = QSlider(Qt.Orientation.Horizontal, tb)
        self._slider_zoom.setRange(140, 240)
        self._slider_zoom.setValue(180)
        self._slider_zoom.setFixedWidth(80)
        self._slider_zoom.valueChanged.connect(self._on_zoom_changed)
        tb_lay.addWidget(self._slider_zoom)

        root.addWidget(tb)

        # ── Scrollable Card View ─────────────────────────────────────────────
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"QScrollArea {{ background: {Colors.BG_CANVAS}; border: none; }}")

        self._container = QWidget()
        self._container.setStyleSheet(f"background: {Colors.BG_CANVAS};")
        self._outer_layout = QVBoxLayout(self._container)
        self._outer_layout.setContentsMargins(0, 0, 0, 8)
        self._outer_layout.setSpacing(0)

        # Flat Grid Section (used when Group by Folder is toggled OFF)
        self._flat_section = QWidget(self._container)
        self._flat_section.setStyleSheet(f"background: {Colors.BG_CANVAS};")
        self._flat_grid = QGridLayout(self._flat_section)
        self._flat_grid.setSpacing(8)
        self._flat_grid.setContentsMargins(10, 8, 10, 8)
        self._outer_layout.addWidget(self._flat_section)
        self._flat_section.setVisible(True)

        self._outer_layout.addStretch()

        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll, stretch=1)

    def _on_filter_all_triggered(self):
        self.reset_filters()

    def _on_filter_item_triggered(self, key: str):
        act = self._filter_actions.get(key)
        if not act:
            return
        if act.isChecked():
            self._active_filters.add(key)
        else:
            self._active_filters.discard(key)

        self._update_filter_button_state()
        self._apply_filter_and_sort()

    def reset_filters(self):
        self._active_filters.clear()
        for act in self._filter_actions.values():
            act.setChecked(False)
        self._act_all.setChecked(True)
        self._update_filter_button_state()
        self._apply_filter_and_sort()

    def _update_filter_button_state(self):
        if not self._active_filters:
            self._act_all.setChecked(True)
            self._btn_filter.setText("🎯 Filter: All ▾")
            self._btn_filter.setToolTip("Filter media by GPS status or media type (multi-select supported)")
            self._btn_filter.setStyleSheet(f"""
                QPushButton#btn_filter_dropdown {{
                    background: {Colors.BG_CARD};
                    border: 1px solid {Colors.BORDER_DEFAULT};
                    border-radius: 6px;
                    color: {Colors.TEXT_PRIMARY};
                    font-size: 11px;
                    font-weight: 500;
                    padding: 4px 10px 4px 10px;
                    min-height: 22px;
                }}
                QPushButton#btn_filter_dropdown:hover {{
                    background: {Colors.BG_CARD_HOVER};
                    border-color: {Colors.CYAN};
                    color: {Colors.CYAN_LIGHT};
                }}
                QPushButton#btn_filter_dropdown::menu-indicator {{
                    subcontrol-origin: padding;
                    subcontrol-position: center right;
                    width: 0px;
                }}
            """)
        else:
            self._act_all.setChecked(False)
            names_map = {
                "missing": "Missing GPS",
                "staged": "Staged",
                "tagged": "Geotagged",
                "videos": "Videos",
                "raw": "RAW Pairs"
            }
            labels = [names_map[k] for k in sorted(self._active_filters) if k in names_map]
            if len(labels) == 1:
                title = f"🎯 {labels[0]} ▾"
            elif len(labels) == 2:
                title = f"🎯 {labels[0]} + {labels[1]} ▾"
            else:
                title = f"🎯 Filters ({len(labels)}) ▾"

            self._btn_filter.setText(title)
            self._btn_filter.setToolTip(f"Active Filters: {', '.join(labels)} (Click to modify)")
            self._btn_filter.setStyleSheet(f"""
                QPushButton#btn_filter_dropdown {{
                    background: {Colors.CYAN_BG};
                    border: 1px solid {Colors.CYAN};
                    border-radius: 6px;
                    color: {Colors.CYAN_LIGHT};
                    font-size: 11px;
                    font-weight: bold;
                    padding: 4px 10px 4px 10px;
                    min-height: 22px;
                }}
                QPushButton#btn_filter_dropdown:hover {{
                    background: #0e4e63;
                    border-color: {Colors.CYAN_LIGHT};
                    color: #ffffff;
                }}
                QPushButton#btn_filter_dropdown::menu-indicator {{
                    subcontrol-origin: padding;
                    subcontrol-position: center right;
                    width: 0px;
                }}
            """)

    def _on_sort_changed(self):
        self._apply_filter_and_sort()

    def _on_zoom_changed(self, val: int):
        self._card_w = val
        self._card_h = int(val * 1.2)
        for cell in self._cells:
            cell.update_size(self._card_w, self._card_h)
        self._last_cols = -1
        self._reflow()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_base_folder(self, folder: Path):
        self._base_folder = folder

    def add_item(self, item: PhotoItem) -> PhotoCell:
        self._all_items.append(item)
        cell = PhotoCell(item, self._card_w, self._card_h)
        cell.clicked.connect(self._on_cell_clicked)
        cell.dbl_clicked.connect(self.photo_activated)
        cell.clear_gps_req.connect(self.clear_gps_req)
        cell.strip_gps_req.connect(self.strip_gps_req)
        cell.show_in_explorer.connect(self.show_in_explorer)
        self._cells.append(cell)
        self._item_to_cell[item] = cell

        folder = item.folder
        if folder not in self._sections:
            section = _FolderSection(folder, self._base_folder, self._container)
            self._sections[folder] = section
            self._outer_layout.insertWidget(self._outer_layout.count() - 1, section)
            section.setVisible(self._group_by_folder)

        cols = self._visible_columns()
        section = self._sections[folder]
        section._cells.append(cell)
        section._header.set_count(len(section._cells))

        if self._group_by_folder:
            cell.setParent(section._grid_widget)
            cell.setVisible(cell.is_filtered_visible)
            idx = len(section._cells) - 1
            row, col = divmod(idx, cols)
            section._grid.addWidget(cell, row, col)
        else:
            cell.setParent(self._flat_section)
            cell.setVisible(cell.is_filtered_visible)
            idx = len(self._cells) - 1
            row, col = divmod(idx, cols)
            self._flat_grid.addWidget(cell, row, col)

        return cell

    def is_grouped_by_folder(self) -> bool:
        return self._group_by_folder

    def set_grouped_by_folder(self, grouped: bool):
        if self._group_by_folder == grouped:
            return
        self._group_by_folder = grouped
        self._btn_group_folder.setChecked(grouped)
        self._btn_group_folder.setText("🗂️ By Folder" if grouped else "🌐 Flat View")
        self._apply_filter_and_sort()

    def _on_group_toggle_clicked(self):
        self.set_grouped_by_folder(self._btn_group_folder.isChecked())

    def clear(self):
        self._reflow_timer.stop()
        while self._flat_grid.count():
            self._flat_grid.takeAt(0)
        for section in self._sections.values():
            section.clear_cells()
            self._outer_layout.removeWidget(section)
            section.deleteLater()
        self._sections.clear()
        self._cells.clear()
        self._item_to_cell.clear()
        self._all_items.clear()
        self._last_idx = None
        self._last_cols = -1
        self._last_group_mode = None
        self._base_folder = None
        self._update_untagged_counter()
        self.selection_changed.emit([])

    def refresh_cell(self, item: PhotoItem):
        cell = self._item_to_cell.get(item)
        if cell:
            cell.refresh()

    def refresh_all(self):
        for cell in self._cells:
            cell.refresh()
        self._update_untagged_counter()

    def selected_items(self) -> list[PhotoItem]:
        return [i for i in self._all_items if i.selected]

    def select_all(self):
        for i in self._all_items:
            i.selected = True
        self.refresh_all()
        self.selection_changed.emit(self.selected_items())

    def deselect_all(self):
        for i in self._all_items:
            i.selected = False
        self.refresh_all()
        self.selection_changed.emit([])

    def select_missing_gps(self):
        for i in self._all_items:
            i.selected = not i.has_gps and not i.has_pending_gps
        self.refresh_all()
        self.selection_changed.emit(self.selected_items())

    def set_search_query(self, query: str):
        self._search_query = query.strip().lower()
        self._apply_filter_and_sort()

    def scroll_to_item(self, item: PhotoItem):
        """Select item and scroll viewport to bring its card into center view."""
        cell = self._item_to_cell.get(item)
        if not cell:
            return

        # If current filter hid the item, reset to "all" to reveal it
        if not cell.isVisible():
            self.reset_filters()

        for i in self._all_items:
            i.selected = (i is item)
        try:
            self._last_idx = self._all_items.index(item)
        except ValueError:
            self._last_idx = None

        self.refresh_all()
        self.selection_changed.emit([item])
        self._scroll.ensureWidgetVisible(cell, 30, 30)

    # ── Jump to Untagged Navigation ──────────────────────────────────────────

    def jump_next_untagged(self):
        """Find the next untagged photo/video (relative to current selection) and scroll to it."""
        if not self._all_items:
            return

        untagged_indices = [
            idx for idx, it in enumerate(self._all_items)
            if not it.has_gps and not it.has_pending_gps
        ]

        if not untagged_indices:
            self.status_message.emit("✓ All photos and videos have GPS coordinates!")
            return

        cur_idx = self._last_idx if self._last_idx is not None else -1

        # Look for first untagged item after cur_idx
        next_indices = [idx for idx in untagged_indices if idx > cur_idx]
        if next_indices:
            target_idx = next_indices[0]
        else:
            # Wrap around to the first untagged item
            target_idx = untagged_indices[0]

        target_item = self._all_items[target_idx]
        rank = untagged_indices.index(target_idx) + 1
        total_untagged = len(untagged_indices)

        self.scroll_to_item(target_item)
        self.status_message.emit(
            f"🔴 Untagged {rank} of {total_untagged}: {target_item.display_name}"
        )
        self._update_untagged_counter()

    def jump_prev_untagged(self):
        """Find the previous untagged photo/video (relative to current selection) and scroll to it."""
        if not self._all_items:
            return

        untagged_indices = [
            idx for idx, it in enumerate(self._all_items)
            if not it.has_gps and not it.has_pending_gps
        ]

        if not untagged_indices:
            self.status_message.emit("✓ All photos and videos have GPS coordinates!")
            return

        cur_idx = self._last_idx if self._last_idx is not None else len(self._all_items)

        # Look for first untagged item before cur_idx (going backwards)
        prev_indices = [idx for idx in untagged_indices if idx < cur_idx]
        if prev_indices:
            target_idx = prev_indices[-1]
        else:
            # Wrap around to the last untagged item
            target_idx = untagged_indices[-1]

        target_item = self._all_items[target_idx]
        rank = untagged_indices.index(target_idx) + 1
        total_untagged = len(untagged_indices)

        self.scroll_to_item(target_item)
        self.status_message.emit(
            f"🔴 Untagged {rank} of {total_untagged}: {target_item.display_name}"
        )
        self._update_untagged_counter()

    def _update_untagged_counter(self):
        n_untagged = sum(1 for it in self._all_items if not it.has_gps and not it.has_pending_gps)
        if n_untagged > 0:
            self._lbl_untagged_count.setText(f"{n_untagged}")
            self._lbl_untagged_count.setVisible(True)
            self._btn_prev_untagged.setEnabled(True)
            self._btn_next_untagged.setEnabled(True)
        else:
            self._lbl_untagged_count.setText("0")
            self._lbl_untagged_count.setVisible(False)
            self._btn_prev_untagged.setEnabled(False)
            self._btn_next_untagged.setEnabled(False)

    # ── Filtering & Sorting ───────────────────────────────────────────────────

    def _apply_filter_and_sort(self):
        active = self._active_filters
        q = self._search_query

        gps_filters = active & {"missing", "staged", "tagged"}
        type_filters = active & {"videos", "raw"}

        for cell in self._cells:
            item = cell.item
            match_filter = True

            if active:
                # GPS Dimension check
                if gps_filters:
                    match_gps = False
                    if "missing" in gps_filters and (not item.has_gps and not item.has_pending_gps):
                        match_gps = True
                    if "staged" in gps_filters and item.has_pending_gps:
                        match_gps = True
                    if "tagged" in gps_filters and item.has_gps:
                        match_gps = True
                    if not match_gps:
                        match_filter = False

                # Type Dimension check
                if match_filter and type_filters:
                    match_type = False
                    if "videos" in type_filters and item.is_video:
                        match_type = True
                    if "raw" in type_filters and (item.is_pair or bool(item.raw_path)):
                        match_type = True
                    if not match_type:
                        match_filter = False

            match_search = True
            if q:
                match_search = (
                    q in item.display_name.lower()
                    or q in str(item.folder).lower()
                    or (item.date_taken and q in item.date_str().lower())
                )

            cell.is_filtered_visible = (match_filter and match_search)
            cell.setVisible(cell.is_filtered_visible)
            cell.show_folder_badge = (not self._group_by_folder and len(self._sections) > 1)

        sort_by = self._combo_sort.currentText()

        # Global sort across all files (used in Flat Mode & navigation)
        if sort_by == "Date Taken":
            self._cells.sort(key=lambda c: c.item.date_taken or datetime.min)
            self._all_items.sort(key=lambda i: i.date_taken or datetime.min)
        elif sort_by == "Filename":
            self._cells.sort(key=lambda c: c.item.display_name.lower())
            self._all_items.sort(key=lambda i: i.display_name.lower())
        elif sort_by == "GPS Status":
            self._cells.sort(key=lambda c: (not c.item.has_gps and not c.item.has_pending_gps, c.item.date_taken or datetime.min))
            self._all_items.sort(key=lambda i: (not i.has_gps and not i.pending.gps and not i.has_gps, i.date_taken or datetime.min))
        elif sort_by == "File Size":
            self._cells.sort(key=lambda c: c.item.file_size_bytes, reverse=True)
            self._all_items.sort(key=lambda i: i.file_size_bytes, reverse=True)

        # Sort cells strictly within their containing folder section (used in Grouped Mode)
        for section in self._sections.values():
            if sort_by == "Date Taken":
                section._cells.sort(key=lambda c: c.item.date_taken or datetime.min)
            elif sort_by == "Filename":
                section._cells.sort(key=lambda c: c.item.display_name.lower())
            elif sort_by == "GPS Status":
                section._cells.sort(key=lambda c: (not c.item.has_gps and not c.item.has_pending_gps, c.item.date_taken or datetime.min))
            elif sort_by == "File Size":
                section._cells.sort(key=lambda c: c.item.file_size_bytes, reverse=True)

            vis_count = sum(1 for c in section.cells if c.is_filtered_visible)
            section._header.set_count(vis_count)

        self._last_cols = -1
        self._reflow()
        self._update_untagged_counter()

    # ── Layout & Reflow ───────────────────────────────────────────────────────

    def _visible_columns(self) -> int:
        w = self._scroll.viewport().width() if self._scroll.viewport() else self.width()
        return max(1, w // (self._card_w + 10))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_timer.stop()
        self._reflow_timer.start(180)

    def _reflow(self):
        cols = self._visible_columns()
        if cols == self._last_cols and self._last_group_mode == self._group_by_folder:
            return
        self._last_cols = cols
        self._last_group_mode = self._group_by_folder

        self._container.setUpdatesEnabled(False)
        try:
            if self._group_by_folder:
                self._flat_section.setVisible(False)
                while self._flat_grid.count():
                    self._flat_grid.takeAt(0)

                for section in self._sections.values():
                    for cell in section.cells:
                        if cell.parentWidget() != section._grid_widget:
                            cell.setParent(section._grid_widget)
                        cell.setVisible(cell.is_filtered_visible)

                    vis_count = sum(1 for c in section.cells if c.is_filtered_visible)
                    section.setVisible(vis_count > 0)
                    section.reflow(cols)
            else:
                for section in self._sections.values():
                    section.setVisible(False)
                    while section._grid.count():
                        section._grid.takeAt(0)

                self._flat_section.setVisible(True)
                while self._flat_grid.count():
                    self._flat_grid.takeAt(0)

                vis_cells = [c for c in self._cells if c.is_filtered_visible]
                for idx, cell in enumerate(vis_cells):
                    if cell.parentWidget() != self._flat_section:
                        cell.setParent(self._flat_section)
                    cell.setVisible(True)
                    row, col = divmod(idx, cols)
                    self._flat_grid.addWidget(cell, row, col)
        finally:
            self._container.setUpdatesEnabled(True)

    # ── Selection ─────────────────────────────────────────────────────────────

    def _on_cell_clicked(self, item: PhotoItem, ctrl: bool, shift: bool):
        try:
            idx = self._all_items.index(item)
        except ValueError:
            return

        if shift and self._last_idx is not None:
            lo, hi = min(idx, self._last_idx), max(idx, self._last_idx)
            if not ctrl:
                for i in self._all_items:
                    i.selected = False
            for i in range(lo, hi + 1):
                self._all_items[i].selected = True
        elif ctrl:
            item.selected = not item.selected
            self._last_idx = idx
        else:
            for i in self._all_items:
                i.selected = False
            item.selected = True
            self._last_idx = idx

        self.refresh_all()
        self.selection_changed.emit(self.selected_items())

    # ── Keyboard Navigation ───────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right):
            cols = self._visible_columns()
            cur = self._last_idx or 0
            if key == Qt.Key.Key_Right:
                nxt = min(len(self._all_items) - 1, cur + 1)
            elif key == Qt.Key.Key_Left:
                nxt = max(0, cur - 1)
            elif key == Qt.Key.Key_Down:
                nxt = min(len(self._all_items) - 1, cur + cols)
            else:
                nxt = max(0, cur - cols)

            if nxt < len(self._all_items):
                shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                ctrl  = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                self._on_cell_clicked(self._all_items[nxt], ctrl, shift)
        else:
            super().keyPressEvent(event)
