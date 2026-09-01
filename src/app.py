"""app.py — Main application window with IIS Sentinel Cyber-Dark UI, Reverse Geocoding, Session Recovery, and Hybrid GPU Stability."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, QTimer, Signal, Slot, QSettings
from PySide6.QtGui import QAction, QKeySequence, QDragEnterEvent, QDropEvent, QPixmap, QImage
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QToolBar, QPushButton, QLabel, QStatusBar, QFileDialog,
    QProgressBar, QMessageBox, QCheckBox, QDoubleSpinBox,
    QGroupBox, QFrame, QApplication, QLineEdit, QMenu,
    QDialog, QDialogButtonBox, QTextEdit,
)

from resources.theme import Colors, STYLE_MODERN_CYBER
from .photo_item import PhotoItem
from .photo_grid import PhotoGrid
from .map_widget import MapWidget
from .photo_preview import PhotoInfoBar
from .workers import ScanThread, ThumbnailThread, SaveThread
from .auto_tagger import auto_tag_by_time, preview_auto_tag
from .photo_manager import EXIFTOOL_PATH, _detect_format_ext
from .backup_manager import BackupService, BackupManagerDialog
from .thumbnail_cache import thumbnail_cache
from .session_manager import session_manager
from .folder_dialog import MultiFolderDialog
from .save_progress_dialog import SaveProgressDialog

log = logging.getLogger(__name__)

APP_TITLE = "GeoTag Studio PRO"
ORG_NAME  = "GeoTag"

SETTINGS_GEOMETRY      = "window/geometry"
SETTINGS_SPLITTER_H    = "window/splitter_h"
SETTINGS_LAST_DIR      = "io/last_folder"
SETTINGS_GAP           = "autotag/gap_minutes"
SETTINGS_INTERP        = "autotag/use_interpolation"
SETTINGS_NORM_DATES    = "save/normalize_dates"
SETTINGS_RENAME        = "save/rename"
SETTINGS_APPEND        = "save/append_original"
SETTINGS_SMART_UNDATED = "save/smart_undated_only"


# ─────────────────────────────────────────────────────────────────────────────
# Warnings Dialog
# ─────────────────────────────────────────────────────────────────────────────

class WarningsDialog(QDialog):
    def __init__(self, warnings: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Save Warnings & Errors")
        self.setMinimumSize(640, 320)
        self.setStyleSheet(STYLE_MODERN_CYBER)
        layout = QVBoxLayout(self)

        te = QTextEdit(self)
        te.setReadOnly(True)
        te.setPlainText("\n".join(warnings))
        te.setStyleSheet(
            f"background:{Colors.BG_INPUT}; color:{Colors.AMBER_LIGHT}; font-family:Consolas; font-size:12px; border:1px solid {Colors.BORDER_DEFAULT};"
        )
        layout.addWidget(te)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        bb.accepted.connect(self.accept)
        layout.addWidget(bb)


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setStyleSheet(STYLE_MODERN_CYBER)
        self.setAcceptDrops(True)

        self._settings = QSettings(ORG_NAME, APP_TITLE)
        self._backup_service = BackupService()
        self._current_folder: Optional[Path] = None
        self._current_folders: list[Path] = []

        self._scan_thread:  Optional[ScanThread]      = None
        self._thumb_thread: Optional[ThumbnailThread] = None
        self._save_thread:  Optional[SaveThread]      = None
        self._save_dialog:  Optional[SaveProgressDialog] = None

        self._selected_gps: Optional[tuple[float, float]] = None
        self._all_items:    list[PhotoItem] = []
        self._is_busy:      bool = False
        self._last_save_stats: dict = {}

        self._ui_update_timer = QTimer(self)
        self._ui_update_timer.setSingleShot(True)
        self._ui_update_timer.setInterval(150)
        self._ui_update_timer.timeout.connect(self._update_action_states)

        if not EXIFTOOL_PATH:
            QTimer.singleShot(500, self._warn_no_exiftool)

        # Asynchronously clean cache older than 30 days on startup
        QTimer.singleShot(1500, self._auto_clean_cache)

        self._build_header()
        self._build_stat_cards()
        self._build_central()
        self._build_statusbar()
        self._build_shortcuts()
        self._restore_settings()

    def _auto_clean_cache(self):
        try:
            cleaned = thumbnail_cache.cleanup_old_cache(max_days=30)
            if cleaned > 0:
                log.info("Startup auto-clean: removed %d expired thumbnail cache files", cleaned)
        except Exception as exc:
            log.warning("Startup cache cleanup: %s", exc)

    # =========================================================================
    # Header Bar (IIS Sentinel Style)
    # =========================================================================

    def _build_header(self):
        header_widget = QWidget(self)
        header_widget.setStyleSheet(
            f"background: {Colors.BG_PANEL}; border-bottom: 1px solid {Colors.BORDER_DEFAULT};"
        )
        header_widget.setFixedHeight(56)
        hl = QHBoxLayout(header_widget)
        hl.setContentsMargins(14, 8, 14, 8)
        hl.setSpacing(12)

        # ── Brand Logo & Title ───────────────────────────────────────────────
        brand_icon = QLabel("🌐", header_widget)
        brand_icon.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {Colors.CYAN}, stop:1 {Colors.BLUE});"
            " border-radius: 8px; font-size: 18px; padding: 4px;"
        )
        hl.addWidget(brand_icon)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        title_lbl = QLabel(APP_TITLE, header_widget)
        title_lbl.setStyleSheet(f"font-size: 14px; font-weight: 800; color: {Colors.TEXT_PRIMARY}; letter-spacing: 0.5px;")
        sub_lbl = QLabel("Modern Geotagging & Metadata Studio (Photos & Videos)", header_widget)
        sub_lbl.setStyleSheet(f"font-size: 10px; color: {Colors.TEXT_MUTED};")
        title_col.addWidget(title_lbl)
        title_col.addWidget(sub_lbl)
        hl.addLayout(title_col)

        hl.addSpacing(10)

        # ── Folder Open / Path Breadcrumb ────────────────────────────────────
        self._btn_open = QPushButton("📁  Open Folder", header_widget)
        self._btn_open.clicked.connect(self._open_folder)
        self._btn_open.setToolTip("Open photos and videos folder recursively (Ctrl+O or Drag & Drop)")
        hl.addWidget(self._btn_open)

        self._lbl_folder = QLabel("No folder loaded", header_widget)
        self._lbl_folder.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px; font-family: Consolas;")
        self._lbl_folder.setMaximumWidth(320)
        hl.addWidget(self._lbl_folder)

        hl.addStretch()

        # ── Search Input ─────────────────────────────────────────────────────
        self._search_input = QLineEdit(header_widget)
        self._search_input.setPlaceholderText("🔍  Filter media...")
        self._search_input.setFixedWidth(150)
        self._search_input.textChanged.connect(lambda q: self._grid.set_search_query(q))
        hl.addWidget(self._search_input)

        # ── Cache Menu Button ────────────────────────────────────────────────
        self._btn_cache = QPushButton("⚡ Cache", header_widget)
        self._btn_cache.setToolTip("Thumbnail Disk Cache (.cache/thumbnails/) — auto-cleans after 30 days")
        cache_menu = QMenu(self)
        cache_menu.setStyleSheet(STYLE_MODERN_CYBER)
        act_open_cache = cache_menu.addAction("📁  Open Cache Folder in Explorer")
        act_open_cache.triggered.connect(self._open_cache_folder)
        act_clear_cache = cache_menu.addAction("🗑️  Clear All Cached Thumbnails")
        act_clear_cache.triggered.connect(self._clear_cache)
        self._btn_cache.setMenu(cache_menu)
        hl.addWidget(self._btn_cache)

        # ── Backup Center Button ─────────────────────────────────────────────
        self._btn_backups = QPushButton("🛡️  Backups", header_widget)
        self._btn_backups.setObjectName("btn_action_purple")
        self._btn_backups.setToolTip("Open Backup Center & Restore Manager (Ctrl+B)")
        self._btn_backups.clicked.connect(self._open_backup_manager)
        hl.addWidget(self._btn_backups)

        # ── Auto-tag CTA ─────────────────────────────────────────────────────
        self._btn_hdr_auto = QPushButton("⚡  Auto-tag", header_widget)
        self._btn_hdr_auto.setObjectName("btn_action_emerald")
        self._btn_hdr_auto.setEnabled(False)
        self._btn_hdr_auto.clicked.connect(self._auto_tag)
        hl.addWidget(self._btn_hdr_auto)

        # ── Save Changes CTA ─────────────────────────────────────────────────
        self._btn_hdr_save = QPushButton("💾  Save Changes", header_widget)
        self._btn_hdr_save.setObjectName("btn_primary")
        self._btn_hdr_save.setEnabled(False)
        self._btn_hdr_save.clicked.connect(self._save_changes)
        hl.addWidget(self._btn_hdr_save)

        self._header_widget = header_widget

    # =========================================================================
    # Real-Time Stat Cards (IIS Log Viewer Style)
    # =========================================================================

    def _build_stat_cards(self):
        cards_widget = QWidget(self)
        cards_widget.setStyleSheet(
            f"background: {Colors.BG_CANVAS}; border-bottom: 1px solid {Colors.BORDER_DEFAULT};"
        )
        cards_widget.setFixedHeight(74)
        cl = QHBoxLayout(cards_widget)
        cl.setContentsMargins(12, 6, 12, 6)
        cl.setSpacing(10)

        self._sc_total   = self._make_stat_card("TOTAL MEDIA", "0", Colors.CYAN, "📷")
        self._sc_tagged  = self._make_stat_card("GEOTAGGED", "0 (0%)", Colors.EMERALD, "📍")
        self._sc_missing = self._make_stat_card("MISSING GPS", "0", Colors.ROSE, "🔴")
        self._sc_staged  = self._make_stat_card("STAGED PENDING", "0", Colors.AMBER, "⏳")
        self._sc_videos  = self._make_stat_card("VIDEOS", "0", Colors.BLUE, "🎬")
        self._sc_backups = self._make_stat_card("BACKUPS SAVED", "0", Colors.PURPLE, "🛡️")

        cl.addWidget(self._sc_total)
        cl.addWidget(self._sc_tagged)
        cl.addWidget(self._sc_missing)
        cl.addWidget(self._sc_staged)
        cl.addWidget(self._sc_videos)
        cl.addWidget(self._sc_backups)

        self._cards_widget = cards_widget

    def _make_stat_card(self, title: str, val: str, accent: str, icon: str) -> QFrame:
        card = QFrame(self)
        card.setStyleSheet(
            f"QFrame {{ background: {Colors.BG_CARD}; border: 1px solid {Colors.BORDER_CARD}; border-radius: 8px; }}"
        )
        card.setFixedHeight(62)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(8)

        icon_lbl = QLabel(icon, card)
        icon_lbl.setStyleSheet("font-size: 18px;")
        lay.addWidget(icon_lbl)

        v = QVBoxLayout()
        v.setSpacing(1)
        v.setContentsMargins(0, 0, 0, 0)
        t_lbl = QLabel(title, card)
        t_lbl.setStyleSheet(f"font-size: 9px; font-weight: bold; color: {Colors.TEXT_MUTED}; letter-spacing: 0.5px;")
        v_lbl = QLabel(val, card)
        v_lbl.setObjectName("val_label")
        v_lbl.setStyleSheet(f"font-size: 13px; font-weight: 800; color: {accent};")
        v.addWidget(t_lbl)
        v.addWidget(v_lbl)
        lay.addLayout(v, stretch=1)
        return card

    # =========================================================================
    # Central Layout
    # =========================================================================

    def _build_central(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._header_widget)
        root.addWidget(self._cards_widget)

        # ── Splitter: Grid (Left) | Map & Action Panel (Right) ───────────────
        self._splitter_h = QSplitter(Qt.Orientation.Horizontal, central)
        self._splitter_h.setChildrenCollapsible(False)

        self._grid = PhotoGrid(self._splitter_h)
        self._grid.selection_changed.connect(self._on_selection_changed)
        self._grid.photo_activated.connect(self._on_photo_activated)
        self._grid.clear_gps_req.connect(self._clear_pending_gps_item)
        self._grid.strip_gps_req.connect(self._strip_gps_item)
        self._grid.show_in_explorer.connect(self._show_in_explorer)
        self._grid.status_message.connect(self._status)
        self._splitter_h.addWidget(self._grid)

        # ── Right side container ─────────────────────────────────────────────
        right = QWidget(self._splitter_h)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._map = MapWidget(right)
        self._map.location_picked.connect(self._on_location_picked)
        self._map.photo_marker_clicked.connect(self._on_photo_marker_clicked)
        right_layout.addWidget(self._map, stretch=1)

        self._info_bar = PhotoInfoBar(right)
        self._info_bar.locate_requested.connect(self._show_in_explorer)
        right_layout.addWidget(self._info_bar)

        right_layout.addWidget(self._build_action_panel(right))

        self._splitter_h.addWidget(right)
        self._splitter_h.setSizes([580, 860])

        # Rigid minimum constraints to prevent panel shifting on long filenames
        self._grid.setMinimumWidth(360)
        right.setMinimumWidth(440)

        root.addWidget(self._splitter_h, stretch=1)

        # Progress bar
        self._progress = QProgressBar(central)
        self._progress.setFixedHeight(4)
        self._progress.setVisible(False)
        self._progress.setTextVisible(False)
        root.addWidget(self._progress)

    def _build_action_panel(self, parent: QWidget) -> QWidget:
        panel = QFrame(parent)
        panel.setStyleSheet(
            f"QFrame {{ background: {Colors.BG_PANEL}; border-top: 1px solid {Colors.BORDER_DEFAULT}; }}"
        )
        panel.setFixedHeight(275)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(6)

        # Row 1: Target Location + Assign GPS / Clear / Strip
        r1 = QHBoxLayout()
        gps_box = QGroupBox("Target Coordinates", panel)
        gl = QHBoxLayout(gps_box)
        self._lbl_gps = QLabel("Click map or paste coordinates above", gps_box)
        self._lbl_gps.setStyleSheet(f"color: {Colors.CYAN_LIGHT}; font-family: Consolas; font-size: 11px; font-weight: bold;")
        gl.addWidget(self._lbl_gps)

        vcol = QVBoxLayout()
        vcol.setSpacing(4)
        self._btn_assign = QPushButton("📍  Assign GPS to Selected", panel)
        self._btn_assign.setObjectName("btn_primary")
        self._btn_assign.setEnabled(False)
        self._btn_assign.clicked.connect(self._assign_gps)
        vcol.addWidget(self._btn_assign)

        sub_btn_row = QHBoxLayout()
        sub_btn_row.setSpacing(4)
        self._btn_clear_sel = QPushButton("✕  Clear Staged", panel)
        self._btn_clear_sel.setObjectName("btn_action_amber")
        self._btn_clear_sel.setEnabled(False)
        self._btn_clear_sel.setToolTip("Cancel pending staged GPS changes for selected photos")
        self._btn_clear_sel.clicked.connect(self._clear_pending_gps_selected)
        sub_btn_row.addWidget(self._btn_clear_sel)

        self._btn_strip_sel = QPushButton("🗑️  Strip GPS", panel)
        self._btn_strip_sel.setObjectName("btn_action_rose")
        self._btn_strip_sel.setEnabled(False)
        self._btn_strip_sel.setToolTip("Erase / delete existing GPS tags from selected files upon saving")
        self._btn_strip_sel.clicked.connect(self._strip_gps_selected)
        sub_btn_row.addWidget(self._btn_strip_sel)

        vcol.addLayout(sub_btn_row)

        r1.addWidget(gps_box, stretch=1)
        r1.addLayout(vcol)
        lay.addLayout(r1)

        # Row 2: Auto-tag controls
        r2 = QHBoxLayout()
        auto_box = QGroupBox("Smart Auto-Tagging (Timeline Anchor for Photos & Videos)", panel)
        al = QHBoxLayout(auto_box)
        al.addWidget(QLabel("Time Window:"))
        self._spin_gap = QDoubleSpinBox(panel)
        self._spin_gap.setRange(0.1, 120.0)
        self._spin_gap.setSingleStep(0.5)
        self._spin_gap.setValue(3.0)
        self._spin_gap.setSuffix(" min")
        self._spin_gap.setFixedWidth(90)
        al.addWidget(self._spin_gap)

        self._chk_interp = QCheckBox("Interpolate GPS between anchors", auto_box)
        self._chk_interp.setChecked(True)
        al.addWidget(self._chk_interp)
        al.addStretch()

        self._btn_auto = QPushButton("⚡  Auto-tag Media", panel)
        self._btn_auto.setObjectName("btn_action_emerald")
        self._btn_auto.setEnabled(False)
        self._btn_auto.clicked.connect(self._auto_tag)
        r2.addWidget(auto_box, stretch=1)
        r2.addWidget(self._btn_auto)
        lay.addLayout(r2)

        # Row 3: Save & Rename Options
        r3 = QHBoxLayout()
        opts_box = QGroupBox("Save & Preservation Options (Originals mirrored to backups/ before write)", panel)
        ol = QHBoxLayout(opts_box)
        ol.setSpacing(10)

        self._chk_norm_dates = QCheckBox("Normalize dates → Date Taken", opts_box)
        self._chk_norm_dates.setChecked(True)
        ol.addWidget(self._chk_norm_dates)

        sep = QFrame(opts_box)
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {Colors.BORDER_DEFAULT};")
        ol.addWidget(sep)

        self._chk_rename = QCheckBox("Rename YYYYMMDD HHMMSS", opts_box)
        ol.addWidget(self._chk_rename)

        self._chk_append_orig = QCheckBox("+ original name", opts_box)
        self._chk_append_orig.setEnabled(False)
        ol.addWidget(self._chk_append_orig)

        self._chk_smart_undated = QCheckBox("⚡ Smart Rename (Undated only)", opts_box)
        self._chk_smart_undated.setToolTip("Preserve already-dated files (e.g. YYYY-MM-DD or YYYYMMDD); only rename undated files.")
        self._chk_smart_undated.setEnabled(False)
        ol.addWidget(self._chk_smart_undated)

        self._chk_rename.toggled.connect(self._on_rename_toggled)

        ol.addStretch()
        r3.addWidget(opts_box, stretch=1)
        lay.addLayout(r3)

        # Row 4: Summary & Save Button
        r4 = QHBoxLayout()
        self._lbl_sel_info = QLabel("No media loaded", panel)
        self._lbl_sel_info.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 11px;")
        r4.addWidget(self._lbl_sel_info, stretch=1)

        self._btn_save = QPushButton("💾  Save All Changes", panel)
        self._btn_save.setObjectName("btn_primary")
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._save_changes)
        r4.addWidget(self._btn_save)
        lay.addLayout(r4)

        return panel

    def _on_rename_toggled(self, checked: bool):
        self._chk_append_orig.setEnabled(checked)
        self._chk_smart_undated.setEnabled(checked)
        if not checked:
            self._chk_append_orig.setChecked(False)
            self._chk_smart_undated.setChecked(False)

    def _build_statusbar(self):
        sb = QStatusBar(self)
        self.setStatusBar(sb)
        self._lbl_status = QLabel("Ready")
        sb.addWidget(self._lbl_status, 1)
        hint = QLabel("Ctrl+O Open | F3/Shift+F3 Next/Prev Untagged | Ctrl+↵ Assign | Del Clear | Ctrl+B Backups | Ctrl+S Save")
        hint.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 11px;")
        sb.addPermanentWidget(hint)

    def _build_shortcuts(self):
        def _act(key, slot):
            a = QAction(self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(slot)
            self.addAction(a)

        _act("Ctrl+O",      self._open_folder)
        _act("Ctrl+A",      self._grid.select_all)
        _act("Escape",      self._grid.deselect_all)
        _act("F3",          self._grid.jump_next_untagged)
        _act("Shift+F3",    self._grid.jump_prev_untagged)
        _act("Alt+Down",    self._grid.jump_next_untagged)
        _act("Alt+Up",      self._grid.jump_prev_untagged)
        _act("Ctrl+Return", self._assign_gps)
        _act("Ctrl+S",      self._save_changes)
        _act("Ctrl+B",      self._open_backup_manager)
        _act("Delete",      self._clear_pending_gps_selected)
        _act("Backspace",   self._clear_pending_gps_selected)

    # =========================================================================
    # Drag and Drop
    # =========================================================================

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        dirs: list[Path] = []
        files: list[Path] = []
        for url in event.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_dir() and p not in dirs:
                dirs.append(p)
            elif p.is_file():
                files.append(p)

        if dirs:
            self._load_folders(dirs)
        elif files:
            parent_dirs = list({f.parent for f in files})
            self._load_folders(parent_dirs)

    # =========================================================================
    # Settings persistence
    # =========================================================================

    def _restore_settings(self):
        geom = self._settings.value(SETTINGS_GEOMETRY)
        if geom:
            self.restoreGeometry(geom)
        else:
            self.resize(1440, 920)

        splitter_sizes = self._settings.value(SETTINGS_SPLITTER_H)
        if splitter_sizes:
            try:
                self._splitter_h.restoreState(splitter_sizes)
            except Exception:
                self._splitter_h.setSizes([580, 860])

        gap = self._settings.value(SETTINGS_GAP, 3.0, type=float)
        self._spin_gap.setValue(gap)

        interp = self._settings.value(SETTINGS_INTERP, True, type=bool)
        self._chk_interp.setChecked(interp)

        norm = self._settings.value(SETTINGS_NORM_DATES, True, type=bool)
        self._chk_norm_dates.setChecked(norm)

        rename = self._settings.value(SETTINGS_RENAME, False, type=bool)
        self._chk_rename.setChecked(rename)

        append = self._settings.value(SETTINGS_APPEND, False, type=bool)
        self._chk_append_orig.setChecked(append)
        self._chk_append_orig.setEnabled(rename)

        smart_undated = self._settings.value(SETTINGS_SMART_UNDATED, False, type=bool)
        self._chk_smart_undated.setChecked(smart_undated)
        self._chk_smart_undated.setEnabled(rename)

        self._refresh_stat_cards()

    def _save_settings(self):
        self._settings.setValue(SETTINGS_GEOMETRY,      self.saveGeometry())
        self._settings.setValue(SETTINGS_SPLITTER_H,    self._splitter_h.saveState())
        self._settings.setValue(SETTINGS_GAP,           self._spin_gap.value())
        self._settings.setValue(SETTINGS_INTERP,        self._chk_interp.isChecked())
        self._settings.setValue(SETTINGS_NORM_DATES,    self._chk_norm_dates.isChecked())
        self._settings.setValue(SETTINGS_RENAME,        self._chk_rename.isChecked())
        self._settings.setValue(SETTINGS_APPEND,        self._chk_append_orig.isChecked())
        self._settings.setValue(SETTINGS_SMART_UNDATED, self._chk_smart_undated.isChecked())
        self._settings.sync()

    # =========================================================================
    # Folder loading & Scanning
    # =========================================================================

    def _open_folder(self):
        last = self._settings.value(SETTINGS_LAST_DIR, str(Path.home() / "Pictures"), type=str)
        init_dir = os.path.normpath(str(last)) if last and Path(last).exists() else str(Path.home() / "Pictures")
        log.info("Opening multi-folder dialog starting at: %s", init_dir)

        dlg = MultiFolderDialog(self, "Select Photo & Video Folders (Hold Ctrl/Shift to pick multiple)", init_dir)
        if dlg.exec():
            folders = dlg.selected_folders()
            if folders:
                self._settings.setValue(SETTINGS_LAST_DIR, os.path.normpath(str(folders[0].resolve())))
                self._settings.sync()
                self._load_folders(folders)

    def _load_folders(self, folders: list[Path]):
        if not folders:
            return
        self._current_folders = list(folders)
        self._current_folder = folders[0]
        self._settings.setValue(SETTINGS_LAST_DIR, os.path.normpath(str(folders[0].resolve())))
        self._settings.sync()

        for t in [self._scan_thread, self._thumb_thread]:
            if t and t.isRunning():
                if hasattr(t, "cancel"):
                    t.cancel()
                t.wait(2000)

        self._grid.clear()
        try:
            if len(folders) == 1:
                common_base = folders[0]
            else:
                common_base = Path(os.path.commonpath([str(f.resolve()) for f in folders]))
        except Exception:
            common_base = folders[0].parent

        self._grid.set_base_folder(common_base)
        self._all_items.clear()
        self._selected_gps = None
        self._info_bar.set_item(None)

        if len(folders) == 1:
            self._lbl_folder.setText(f"📂 {folders[0].name}")
            self._lbl_folder.setToolTip(str(folders[0]))
            status_desc = str(folders[0])
        else:
            names = ", ".join(f.name for f in folders[:3])
            if len(folders) > 3:
                names += f", +{len(folders) - 3} more"
            self._lbl_folder.setText(f"📂 {len(folders)} Folders ({names})")
            self._lbl_folder.setToolTip("\n".join(str(f) for f in folders))
            status_desc = f"{len(folders)} folders"

        self._map.clear_picker()

        self._status(f"Scanning {status_desc} for photos & videos...")
        self._progress.setRange(0, 0)
        self._progress.setVisible(True)

        self._scan_thread = ScanThread(folders, self)
        self._scan_thread.item_ready.connect(self._on_item_ready)
        self._scan_thread.scan_done.connect(self._on_scan_done)
        self._scan_thread.error.connect(self._on_scan_error)
        self._scan_thread.start()

    def _load_folder(self, folder: Path):
        self._load_folders([folder])

    @Slot(object)
    def _on_item_ready(self, item: PhotoItem):
        self._all_items.append(item)
        self._grid.add_item(item)
        self._ui_update_timer.start()

    @Slot(int)
    def _on_scan_done(self, total: int):
        self._progress.setVisible(False)
        self._refresh_stat_cards()
        self._update_action_states()
        self._map.show_photo_markers(self._all_items)

        # Auto-recover staged state from previous session if any
        recovered = session_manager.get_staged_state(self._current_folders or self._current_folder)
        if recovered:
            n_rec = 0
            for it in self._all_items:
                p_str = str(it.display_path.resolve())
                if p_str in recovered:
                    it.pending.gps = recovered[p_str]
                    n_rec += 1
            if n_rec > 0:
                self._grid.refresh_all()
                self._refresh_stat_cards()
                self._update_action_states()
                self._map.show_photo_markers(self._all_items)
                self._status(f"⚡ Restored {n_rec} staged GPS coordinate(s) from previous session!")

        if not recovered:
            self._status(f"Loaded {total} media items — loading thumbnails in parallel...")

        self._thumb_thread = ThumbnailThread(list(self._all_items), self)
        self._thumb_thread.thumbnail_image_ready.connect(self._on_thumbnail_image_ready)
        self._thumb_thread.all_done.connect(self._on_thumbnails_done)
        self._thumb_thread.start()

    @Slot(str)
    def _on_scan_error(self, msg: str):
        self._progress.setVisible(False)
        QMessageBox.critical(self, "Scan Error", msg)
        self._status("Scan failed.")

    @Slot(object, object)
    def _on_thumbnail_image_ready(self, item: PhotoItem, qimage: QImage):
        item.thumbnail = QPixmap.fromImage(qimage)
        self._grid.refresh_cell(item)
        if self._info_bar._item is item:
            self._info_bar.refresh()

    @Slot()
    def _on_thumbnails_done(self):
        n_miss = sum(1 for i in self._all_items if not i.has_gps)
        self._status(f"✓ Ready — {len(self._all_items)} items loaded, {n_miss} missing GPS")
        self._refresh_stat_cards()

    # =========================================================================
    # Selection & Map Events
    # =========================================================================

    @Slot(list)
    def _on_selection_changed(self, selected: list[PhotoItem]):
        n = len(selected)
        total = len(self._all_items)
        self._lbl_sel_info.setText(f"{n} of {total} selected")
        self._update_action_states()

        self._info_bar.set_item(selected[0] if n == 1 else None)

        if n == 1:
            item = selected[0]
            g = item.effective_gps
            if g:
                self._map.fly_to(g[0], g[1], zoom=16)
                self._selected_gps = g
                self._lbl_gps.setText(f"{g[0]:.6f}, {g[1]:.6f}")
                self._update_action_states()

    @Slot(object)
    def _on_photo_activated(self, item: PhotoItem):
        g = item.effective_gps
        if g:
            self._map.fly_to(g[0], g[1], zoom=17)

    @Slot(float, float, str)
    def _on_location_picked(self, lat: float, lon: float, label: str):
        self._selected_gps = (lat, lon)
        addr_suffix = f"  ({label})" if label else ""
        self._lbl_gps.setText(f"{lat:.6f}, {lon:.6f}{addr_suffix}")
        self._lbl_gps.setToolTip(f"Coordinates: {lat:.6f}, {lon:.6f}\nAddress: {label}" if label else "")
        self._update_action_states()

    @Slot(str, float, float)
    def _on_photo_marker_clicked(self, identifier: str, lat: float, lon: float):
        """When a user clicks on a photo dot on the map, scroll to and select that item in the grid."""
        target: Optional[PhotoItem] = None
        for item in self._all_items:
            if str(item.display_path.resolve()) == identifier or item.display_name == identifier:
                target = item
                break
        if not target:
            for item in self._all_items:
                g = item.effective_gps
                if g and abs(g[0] - lat) < 1e-5 and abs(g[1] - lon) < 1e-5:
                    target = item
                    break

        if target:
            log.info("Scrolled to photo from map click: %s", target.display_name)
            self._grid.scroll_to_item(target)
            self._info_bar.set_item(target)
            self._status(f"📍 Selected {target.display_name} from map location")

    # =========================================================================
    # Assign GPS & Clear Staged
    # =========================================================================

    def _assign_gps(self):
        gps = self._selected_gps or self._map.current_gps
        if not gps:
            self._status("Pick a location on the map or select a geotagged photo first.")
            return
        selected = self._grid.selected_items()
        if not selected:
            self._status("Select photos or videos in the grid first.")
            return

        lat, lon = gps
        self._selected_gps = gps
        for item in selected:
            item.pending.gps = (lat, lon)
            item.pending.strip_gps = False

        # Save session recovery state
        session_manager.save_staged_state(self._current_folders or self._current_folder, self._all_items)

        self._grid.refresh_all()
        self._info_bar.refresh()
        self._map.show_photo_markers(self._all_items)
        self._refresh_stat_cards()
        self._update_action_states()
        self._status(f"📍 Staged GPS ({lat:.6f}, {lon:.6f}) for {len(selected)} item(s). Click 'Save All Changes' to write.")

    def _clear_pending_gps_selected(self):
        selected = [i for i in self._grid.selected_items() if i.has_pending_gps]
        if not selected:
            return
        for item in selected:
            item.pending.gps = None
            item.pending.strip_gps = False

        session_manager.save_staged_state(self._current_folder, self._all_items)

        self._grid.refresh_all()
        self._info_bar.refresh()
        self._map.show_photo_markers(self._all_items)
        self._refresh_stat_cards()
        self._update_action_states()
        self._status(f"Cleared staged GPS changes from {len(selected)} item(s).")

    @Slot(object)
    def _clear_pending_gps_item(self, item: PhotoItem):
        if item.has_pending_gps:
            item.pending.gps = None
            item.pending.strip_gps = False
            session_manager.save_staged_state(self._current_folder, self._all_items)
            self._grid.refresh_cell(item)
            self._info_bar.refresh()
            self._map.show_photo_markers(self._all_items)
            self._refresh_stat_cards()
            self._update_action_states()
            self._status(f"Cleared staged GPS changes from {item.display_name}.")

    def _strip_gps_selected(self):
        selected = [i for i in self._grid.selected_items() if i.has_gps or i.pending.gps]
        if not selected:
            self._status("Select photos or videos with GPS to erase.")
            return
        for item in selected:
            item.pending.gps = None
            item.pending.strip_gps = True

        session_manager.save_staged_state(self._current_folder, self._all_items)

        self._grid.refresh_all()
        self._info_bar.refresh()
        self._map.show_photo_markers(self._all_items)
        self._refresh_stat_cards()
        self._update_action_states()
        self._status(f"🗑️ Staged GPS removal for {len(selected)} item(s). Click 'Save All Changes' to write.")

    @Slot(object)
    def _strip_gps_item(self, item: PhotoItem):
        item.pending.gps = None
        item.pending.strip_gps = True
        session_manager.save_staged_state(self._current_folder, self._all_items)
        self._grid.refresh_cell(item)
        self._info_bar.refresh()
        self._map.show_photo_markers(self._all_items)
        self._refresh_stat_cards()
        self._update_action_states()
        self._status(f"🗑️ Staged GPS removal for {item.display_name}. Click 'Save All Changes' to write.")

    @Slot(object)
    def _show_in_explorer(self, item: PhotoItem):
        try:
            subprocess.Popen(["explorer", "/select,", str(item.display_path.resolve())])
        except Exception as exc:
            log.warning("Explorer open failed: %s", exc)

    # =========================================================================
    # Auto-Tag
    # =========================================================================

    def _auto_tag(self):
        gap = self._spin_gap.value()
        interp = self._chk_interp.isChecked()
        preview = preview_auto_tag(self._all_items, gap, use_interpolation=interp)

        if not preview:
            QMessageBox.information(
                self, "Auto-tag",
                f"No un-tagged photos or videos found within {gap:.1f} minutes of a geotagged anchor.\n\n"
                "Assign GPS to at least one photo or video first, then try again."
            )
            return

        lines = [
            f"Auto-tag will stage GPS on <b>{len(preview)}</b> media item(s) "
            f"within <b>{gap:.1f} min</b> of a geotagged anchor.<br><br>"
            "Sample matches:<br>",
        ]
        for item, gps, desc in preview[:6]:
            icon = "🎬" if item.is_video else "📷"
            lines.append(
                f"&nbsp;&nbsp;• {icon} <b>{item.display_name}</b> → {gps[0]:.5f}, {gps[1]:.5f} <span style='color:#94a3b8;'>({desc})</span><br>"
            )
        if len(preview) > 6:
            lines.append(f"<br>&nbsp;&nbsp;… and {len(preview) - 6} more.")

        reply = QMessageBox.question(
            self, "Confirm Auto-tag", "".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        tagged = auto_tag_by_time(self._all_items, gap, use_interpolation=interp)
        session_manager.save_staged_state(self._current_folder, self._all_items)

        self._grid.refresh_all()
        self._info_bar.refresh()
        self._map.show_photo_markers(self._all_items)
        self._refresh_stat_cards()
        self._update_action_states()
        self._status(f"⚡ Auto-tagged {len(tagged)} item(s) — click 'Save All Changes' to write.")

    # =========================================================================
    # Save Changes (with Backup Engine, Format Conversion & Smart Rename)
    # =========================================================================

    def _save_changes(self):
        norm_dates    = self._chk_norm_dates.isChecked()
        do_rename     = self._chk_rename.isChecked()
        append_orig   = self._chk_append_orig.isChecked()
        smart_undated = self._chk_smart_undated.isChecked() and do_rename

        selected = self._grid.selected_items()
        pending_items = [i for i in self._all_items if i.has_pending_gps]

        if pending_items:
            # When there are staged GPS / strip changes, save ALL staged items
            if do_rename or norm_dates:
                to_save = self._all_items
            else:
                to_save = pending_items
        elif selected and (do_rename or norm_dates):
            to_save = selected
        elif (do_rename or norm_dates) and self._all_items:
            to_save = self._all_items
        else:
            QMessageBox.information(
                self, "Nothing to Save",
                "No media items have pending GPS changes or requested modifications."
            )
            return

        # Check for PNG and format-mismatched files (e.g. .png, PNG disguised as .jpg or .heic.jpg)
        png_or_mismatched = [
            i for i in to_save
            if i.is_png or i.has_format_mismatch or ".heic." in i.display_name.lower()
        ]
        convert_mismatched = bool(png_or_mismatched)

        n_photos_tagged   = sum(1 for i in to_save if (not i.is_video) and i.pending.gps is not None)
        n_videos_tagged   = sum(1 for i in to_save if i.is_video and i.pending.gps is not None)
        n_photos_stripped = sum(1 for i in to_save if (not i.is_video) and i.pending.strip_gps)
        n_videos_stripped = sum(1 for i in to_save if i.is_video and i.pending.strip_gps)
        n_mismatched      = len(png_or_mismatched)

        self._last_save_stats = {
            "photos_tagged": n_photos_tagged,
            "videos_tagged": n_videos_tagged,
            "photos_stripped": n_photos_stripped,
            "videos_stripped": n_videos_stripped,
            "mismatched_converted": n_mismatched,
            "total_items": len(to_save),
            "normalized": len(to_save) if norm_dates else 0,
            "renamed": len(to_save) if do_rename else 0,
        }

        n_files = sum(len(i.all_paths) for i in to_save)
        backup_dir = self._backup_service.backup_root

        rename_desc = (
            f"Smart Rename undated files → YYYYMMDD HHMMSS{'+ original name' if append_orig else ''}.ext (skips already-dated)"
            if smart_undated else
            f"Rename files → YYYYMMDD HHMMSS{'+ original name' if append_orig else ''}.ext"
        )

        ops = []
        if png_or_mismatched:
            ops.append(f"• Back up & convert <b>{len(png_or_mismatched)} PNG / mismatched photo(s)</b> to true JPEG (95% quality) & delete source PNGs")
        if n_photos_tagged:
            ops.append(f"• Write new GPS coordinates to <b>{n_photos_tagged} photo(s)</b>")
        if n_videos_tagged:
            ops.append(f"• Write new GPS coordinates to <b>{n_videos_tagged} video(s)</b>")
        if n_photos_stripped:
            ops.append(f"• Erase / Delete GPS from <b>{n_photos_stripped} photo(s)</b>")
        if n_videos_stripped:
            ops.append(f"• Erase / Delete GPS from <b>{n_videos_stripped} video(s)</b>")
        if norm_dates:
            ops.append(f"• Normalize timestamps → DateTimeOriginal / CreateDate on <b>{len(to_save)} item(s)</b>")
        if do_rename:
            ops.append(f"• {rename_desc} on <b>{len(to_save)} item(s)</b>")

        ops_html = "<br>".join(ops) if ops else f"• Process {len(to_save)} media item(s)"

        body = (
            f"About to process <b>{len(to_save)}</b> media item(s) (<b>{n_files}</b> physical files):<br><br>"
            f"• <b>Original files will be backed up</b> into:<br>"
            f"&nbsp;&nbsp;<span style='color:#67e8f9;font-family:Consolas;'>{backup_dir}</span><br><br>"
            f"<b>Operations to perform:</b><br>"
            f"{ops_html}<br><br>"
            f"<b>All changes are non-destructive with backup restoration available in Backup Center.</b>"
        )

        reply = QMessageBox.question(
            self, "Confirm Save & Backup", body,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._set_busy(True)
        self._progress.setRange(0, len(to_save))
        self._progress.setValue(0)
        self._progress.setVisible(True)

        self._save_dialog = SaveProgressDialog(len(to_save), self)
        self._save_dialog.show()

        self._save_thread = SaveThread(
            items=to_save,
            normalize_dates=norm_dates,
            do_rename=do_rename,
            append_original=append_orig,
            smart_undated_only=smart_undated,
            convert_mismatched=convert_mismatched,
            backup_service=self._backup_service,
            parent=self,
        )
        self._save_thread.progress.connect(self._on_save_progress)
        self._save_thread.done.connect(self._on_save_done)
        self._save_thread.error.connect(self._on_save_error)
        self._save_thread.start()

    @Slot(int, int, str, str)
    def _on_save_progress(self, n: int, total: int, filename: str = "", stage: str = ""):
        self._progress.setValue(n)
        status_msg = f"Saving: {filename} ({n}/{total})" if filename else f"Saving & Backing up... {n} / {total}"
        self._status(status_msg)
        if self._save_dialog:
            self._save_dialog.update_progress(n, total, filename, stage)

    @Slot(list)
    def _on_save_done(self, warnings: list[str]):
        if self._save_dialog:
            self._save_dialog.accept()
            self._save_dialog = None

        self._progress.setVisible(False)
        self._set_busy(False)
        self._refresh_stat_cards()

        # Clear session recovery state now that changes are permanently saved
        session_manager.clear_folder_state(self._current_folders or self._current_folder)

        stats = getattr(self, "_last_save_stats", {})
        details = []
        if stats.get("photos_tagged"):
            details.append(f"• <b>{stats['photos_tagged']} photo(s)</b> geotagged")
        if stats.get("videos_tagged"):
            details.append(f"• <b>{stats['videos_tagged']} video(s)</b> geotagged")
        if stats.get("photos_stripped"):
            details.append(f"• <b>{stats['photos_stripped']} photo(s)</b> GPS removed")
        if stats.get("videos_stripped"):
            details.append(f"• <b>{stats['videos_stripped']} video(s)</b> GPS removed")
        if stats.get("mismatched_converted"):
            details.append(f"• <b>{stats['mismatched_converted']} format-mismatched photo(s)</b> converted to JPEG")
        if stats.get("normalized"):
            details.append(f"• <b>{stats['normalized']} item(s)</b> timestamps normalized")
        if stats.get("renamed"):
            details.append(f"• <b>{stats['renamed']} item(s)</b> renamed")

        details_html = "<br>".join(details) if details else f"• <b>{stats.get('total_items', len(self._all_items))} item(s)</b> processed"

        if warnings:
            WarningsDialog(warnings, self).exec()
            self._status(f"Saved with {len(warnings)} warning(s). Check log.")
        else:
            self._status("✓ All changes written & backed up successfully.")
            QMessageBox.information(
                self, "Save & Backup Complete",
                f"✓ Successfully backed up original files, wrote metadata updates, and applied changes.<br><br>"
                f"{details_html}<br><br>"
                f"• Backups archived in Backup Center<br><br>"
                "Reloading folder to verify all changes on disk..."
            )
            if self._current_folders:
                self._load_folders(self._current_folders)
            elif self._current_folder and self._current_folder.exists():
                self._load_folder(self._current_folder)

    @Slot(str)
    def _on_save_error(self, msg: str):
        if self._save_dialog:
            self._save_dialog.accept()
            self._save_dialog = None

        self._progress.setVisible(False)
        self._set_busy(False)
        QMessageBox.critical(self, "Save Error", msg)
        self._status("Save failed.")

    # =========================================================================
    # Backup & Cache Helpers
    # =========================================================================

    def _open_backup_manager(self):
        dlg = BackupManagerDialog(self, self._backup_service)
        dlg.exec()
        self._refresh_stat_cards()

    def _open_cache_folder(self):
        try:
            cache_p = thumbnail_cache.cache_dir.resolve()
            cache_p.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["explorer", str(cache_p)])
        except Exception as exc:
            log.warning("Explorer cache open error: %s", exc)

    def _clear_cache(self):
        stats = thumbnail_cache.get_stats()
        reply = QMessageBox.question(
            self, "Clear Thumbnail Cache",
            f"Are you sure you want to clear all cached thumbnails?\n\n"
            f"• Files: {stats['count']}\n"
            f"• Size: {stats['formatted_size']}\n"
            f"• Location: {stats['path']}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            n = thumbnail_cache.clear_all()
            self._status(f"Cleared {n} cached thumbnails.")
            QMessageBox.information(self, "Cache Cleared", f"Cleared {n} thumbnail files from disk cache.")

    # =========================================================================
    # Helpers & Stat Cards Refresh
    # =========================================================================

    def _refresh_stat_cards(self):
        total = len(self._all_items)
        n_ok = sum(1 for i in self._all_items if i.has_gps and not i.pending.strip_gps)
        n_miss = sum(1 for i in self._all_items if not i.has_gps and not i.pending.gps)
        n_staged = sum(1 for i in self._all_items if i.has_pending_gps)
        n_vids = sum(1 for i in self._all_items if i.is_video)

        pct = f"({(n_ok / total * 100):.0f}%)" if total > 0 else "(0%)"

        self._sc_total.findChild(QLabel, "val_label").setText(str(total))
        self._sc_tagged.findChild(QLabel, "val_label").setText(f"{n_ok} {pct}")
        self._sc_missing.findChild(QLabel, "val_label").setText(str(n_miss))
        self._sc_staged.findChild(QLabel, "val_label").setText(str(n_staged))
        self._sc_videos.findChild(QLabel, "val_label").setText(str(n_vids))

        stats = self._backup_service.get_storage_stats()
        self._sc_backups.findChild(QLabel, "val_label").setText(str(stats["total_files"]))
        self._btn_backups.setText(f"🛡️  Backups ({stats['total_files']})")

    def _update_action_states(self):
        if getattr(self, "_is_busy", False):
            for w in [self._btn_open, self._btn_assign, self._btn_auto, self._btn_save,
                      self._btn_hdr_auto, self._btn_hdr_save, self._btn_clear_sel, self._btn_strip_sel]:
                w.setEnabled(False)
            return

        has_items   = bool(self._all_items)
        selected    = self._grid.selected_items()
        has_sel     = bool(selected)
        has_map_gps = self._selected_gps is not None or (self._map.current_gps is not None)
        n_pending   = sum(1 for i in self._all_items if i.has_pending_gps)
        has_pending = n_pending > 0
        has_anchors = any(i.effective_gps for i in self._all_items)
        sel_pending = any(i.has_pending_gps for i in selected)
        sel_has_gps = any(i.has_gps or i.pending.gps for i in selected)

        norm_or_rename = self._chk_norm_dates.isChecked() or self._chk_rename.isChecked()

        self._btn_assign.setEnabled(has_sel and has_map_gps)
        self._btn_clear_sel.setEnabled(has_sel and sel_pending)
        self._btn_strip_sel.setEnabled(has_sel and sel_has_gps)
        self._btn_auto.setEnabled(has_items and has_anchors)
        self._btn_hdr_auto.setEnabled(has_items and has_anchors)
        self._btn_save.setEnabled(has_pending or (has_items and norm_or_rename))
        self._btn_hdr_save.setEnabled(has_pending or (has_items and norm_or_rename))

        self._refresh_stat_cards()

    def _set_busy(self, busy: bool):
        self._is_busy = busy
        for w in [self._btn_open, self._btn_assign, self._btn_auto, self._btn_save,
                  self._btn_hdr_auto, self._btn_hdr_save, self._btn_clear_sel, self._btn_strip_sel]:
            w.setEnabled(not busy)
        if not busy:
            self._update_action_states()

    def _status(self, msg: str):
        self._lbl_status.setText(msg)
        log.debug("Status: %s", msg)

    def _warn_no_exiftool(self):
        QMessageBox.warning(
            self, "ExifTool Not Found",
            "ExifTool was not found on this system.\n\n"
            "Download the Windows Executable from:\n"
            "  https://exiftool.org\n\n"
            "Place exiftool.exe in the application folder.",
        )

    def closeEvent(self, event):
        self._save_settings()
        for t in [self._scan_thread, self._thumb_thread, self._save_thread]:
            if t and t.isRunning():
                if hasattr(t, "cancel"):
                    t.cancel()
                t.wait(2000)
        super().closeEvent(event)
