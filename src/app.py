"""app.py — Main application window."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, QTimer, Signal, Slot, QSettings
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QToolBar, QPushButton, QLabel, QStatusBar, QFileDialog,
    QProgressBar, QMessageBox, QCheckBox, QDoubleSpinBox,
    QGroupBox, QFrame, QApplication,
    QDialog, QDialogButtonBox, QTextEdit,
)

from .photo_item import PhotoItem
from .photo_grid import PhotoGrid
from .map_widget import MapWidget
from .photo_preview import PhotoInfoBar
from .workers import ScanThread, ThumbnailThread, SaveThread
from .auto_tagger import auto_tag_by_time, preview_auto_tag
from .photo_manager import EXIFTOOL_PATH

log = logging.getLogger(__name__)

APP_TITLE = "GeoTag Photos"
ORG_NAME  = "GeoTagPhotos"

STYLE_DARK = """
QMainWindow, QWidget          { background: #1a1a2e; color: #e2e8f0; }
QSplitter::handle             { background: #2d3748; width: 3px; height: 3px; }
QPushButton {
    background: #2d3748; color: #e2e8f0;
    border: 1px solid #4a5568; border-radius: 5px;
    padding: 6px 14px; font-size: 12px;
}
QPushButton:hover             { background: #4a5568; }
QPushButton:pressed           { background: #0f3460; }
QPushButton:disabled          { color: #4a5568; border-color: #2d3748; }
QPushButton#btn_primary {
    background: #e94560; border-color: #e94560; color: #fff; font-weight: bold;
}
QPushButton#btn_primary:hover    { background: #c73652; }
QPushButton#btn_primary:disabled { background: #4a2030; border-color: #4a2030; }
QPushButton#btn_assign {
    background: #0f3460; border-color: #1a5276; color: #fff; font-weight: bold;
}
QPushButton#btn_assign:hover     { background: #1a4a80; }
QPushButton#btn_auto  { background: #065f46; border-color: #059669; color: #fff; }
QPushButton#btn_auto:hover       { background: #047857; }
QPushButton#btn_clear { color: #f59e0b; border-color: #78350f; }
QPushButton#btn_clear:hover      { background: #78350f; }
QLabel                        { color: #e2e8f0; }
QLabel#lbl_dim                { color: #94a3b8; font-size: 11px; }
QLabel#lbl_gps                { color: #f59e0b; font-size: 12px; font-weight: bold; }
QLabel#lbl_pending            { color: #f59e0b; font-size: 11px; font-weight: bold; }
QCheckBox                     { color: #e2e8f0; spacing: 6px; }
QCheckBox::indicator {
    width: 15px; height: 15px;
    border: 1px solid #4a5568; border-radius: 3px; background: #2d3748;
}
QCheckBox::indicator:checked  { background: #0f3460; border-color: #e94560; }
QDoubleSpinBox {
    background: #2d3748; color: #e2e8f0; border: 1px solid #4a5568;
    border-radius: 4px; padding: 3px 6px; min-width: 80px;
}
QProgressBar  { background: #2d3748; border: none; border-radius: 3px; }
QProgressBar::chunk { background: #e94560; border-radius: 3px; }
QGroupBox {
    border: 1px solid #2d3748; border-radius: 5px;
    margin-top: 10px; padding-top: 6px; color: #94a3b8; font-size: 11px;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QScrollBar:vertical           { background: #1a1a2e; width: 8px; border: none; }
QScrollBar::handle:vertical   { background: #2d3748; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical { height: 0; }
QStatusBar                    { background: #16213e; color: #94a3b8; font-size: 11px; }
QToolBar    { background: #16213e; border: none; padding: 2px; spacing: 3px; }
QToolBar::separator { background: #2d3748; width: 1px; margin: 4px 2px; }
QMenu       { background: #2d3748; color: #e2e8f0; border: 1px solid #4a5568; }
QMenu::item:selected { background: #0f3460; }
"""

SETTINGS_GEOMETRY   = "window/geometry"
SETTINGS_SPLITTER_H = "window/splitter_h"
SETTINGS_SPLITTER_V = "window/splitter_v"
SETTINGS_LAST_DIR   = "io/last_folder"
SETTINGS_GAP        = "autotag/gap_minutes"
SETTINGS_NORM_DATES = "save/normalize_dates"
SETTINGS_RENAME     = "save/rename"
SETTINGS_APPEND     = "save/append_original"


# ──────────────────────────────────────────────────────────────────────────────
# Warnings dialog
# ──────────────────────────────────────────────────────────────────────────────

class WarningsDialog(QDialog):
    def __init__(self, warnings: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Save — Warnings / Errors")
        self.setMinimumSize(640, 320)
        layout = QVBoxLayout(self)
        te = QTextEdit(self)
        te.setReadOnly(True)
        te.setPlainText("\n".join(warnings))
        te.setStyleSheet(
            "background:#2d3748; color:#fbbf24; font-family:Consolas; font-size:12px;"
        )
        layout.addWidget(te)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        bb.accepted.connect(self.accept)
        layout.addWidget(bb)


# ──────────────────────────────────────────────────────────────────────────────
# Main window
# ──────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setStyleSheet(STYLE_DARK)

        self._settings = QSettings(ORG_NAME, APP_TITLE)

        self._scan_thread:  Optional[ScanThread]      = None
        self._thumb_thread: Optional[ThumbnailThread] = None
        self._save_thread:  Optional[SaveThread]      = None

        self._selected_gps: Optional[tuple[float, float]] = None
        self._all_items:    list[PhotoItem] = []

        self._ui_update_timer = QTimer(self)
        self._ui_update_timer.setSingleShot(True)
        self._ui_update_timer.setInterval(200)
        self._ui_update_timer.timeout.connect(self._update_action_states)

        if not EXIFTOOL_PATH:
            QTimer.singleShot(500, self._warn_no_exiftool)

        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self._build_shortcuts()
        self._restore_settings()

    # =========================================================================
    # UI construction
    # =========================================================================

    def _build_toolbar(self):
        tb = QToolBar("Main", self)
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        self.addToolBar(tb)

        self._btn_open = QPushButton("📁  Open Folder")
        self._btn_open.clicked.connect(self._open_folder)
        self._btn_open.setToolTip("Open a photo folder recursively (Ctrl+O)")
        tb.addWidget(self._btn_open)

        tb.addSeparator()

        self._btn_sel_all = QPushButton("☑  Select All")
        self._btn_sel_all.clicked.connect(lambda: self._grid.select_all())
        self._btn_sel_all.setEnabled(False)
        self._btn_sel_all.setToolTip("Select all photos (Ctrl+A)")
        tb.addWidget(self._btn_sel_all)

        self._btn_sel_none = QPushButton("☐  Deselect")
        self._btn_sel_none.clicked.connect(lambda: self._grid.deselect_all())
        self._btn_sel_none.setEnabled(False)
        self._btn_sel_none.setToolTip("Deselect all (Escape)")
        tb.addWidget(self._btn_sel_none)

        self._btn_sel_missing = QPushButton("🔴  Select Missing GPS")
        self._btn_sel_missing.clicked.connect(lambda: self._grid.select_missing_gps())
        self._btn_sel_missing.setEnabled(False)
        self._btn_sel_missing.setToolTip("Select every photo that has no GPS data")
        tb.addWidget(self._btn_sel_missing)

        tb.addSeparator()

        self._lbl_pending = QLabel("")
        self._lbl_pending.setObjectName("lbl_pending")
        self._lbl_pending.setVisible(False)
        tb.addWidget(self._lbl_pending)

        self._lbl_folder = QLabel("  No folder open")
        self._lbl_folder.setObjectName("lbl_dim")
        tb.addWidget(self._lbl_folder)

    def _build_central(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Horizontal splitter: grid | right panel ───────────────────────────
        self._splitter_h = QSplitter(Qt.Orientation.Horizontal, central)
        self._splitter_h.setChildrenCollapsible(False)

        self._grid = PhotoGrid(self._splitter_h)
        self._grid.selection_changed.connect(self._on_selection_changed)
        self._grid.photo_activated.connect(self._on_photo_activated)
        self._grid.clear_gps_req.connect(self._clear_pending_gps_item)
        self._grid.show_in_explorer.connect(self._show_in_explorer)
        self._splitter_h.addWidget(self._grid)

        # ── Right side: vertical splitter map | preview bar | action panel ────
        right = QWidget(self._splitter_h)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._map = MapWidget(right)
        self._map.location_picked.connect(self._on_location_picked)
        right_layout.addWidget(self._map, stretch=1)

        # Photo info bar (hidden until a single photo is selected)
        self._info_bar = PhotoInfoBar(right)
        self._info_bar.locate_requested.connect(self._show_in_explorer)
        right_layout.addWidget(self._info_bar)

        right_layout.addWidget(self._build_action_panel(right))

        self._splitter_h.addWidget(right)
        self._splitter_h.setSizes([530, 910])

        root.addWidget(self._splitter_h, stretch=1)

        self._progress = QProgressBar(central)
        self._progress.setFixedHeight(5)
        self._progress.setVisible(False)
        self._progress.setTextVisible(False)
        root.addWidget(self._progress)

    def _build_action_panel(self, parent: QWidget) -> QWidget:
        panel = QFrame(parent)
        panel.setStyleSheet(
            "QFrame { background:#16213e; border-top:1px solid #2d3748; }"
        )
        panel.setFixedHeight(218)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(6)

        # Row 1: Map location + Assign + Clear
        r1 = QHBoxLayout()
        gps_box = QGroupBox("Selected Map Location", panel)
        gl = QHBoxLayout(gps_box)
        self._lbl_gps = QLabel("Click the map to pick a location", gps_box)
        self._lbl_gps.setObjectName("lbl_gps")
        gl.addWidget(self._lbl_gps)

        vcol = QVBoxLayout()
        vcol.setSpacing(4)
        self._btn_assign = QPushButton("📍  Assign GPS to Selected", panel)
        self._btn_assign.setObjectName("btn_assign")
        self._btn_assign.setEnabled(False)
        self._btn_assign.clicked.connect(self._assign_gps)
        self._btn_assign.setToolTip(
            "Assign the picked map location to selected photos (Ctrl+Return).\n"
            "Changes are staged — click 'Save' to write to disk."
        )
        vcol.addWidget(self._btn_assign)

        self._btn_clear_sel = QPushButton("✕  Clear Pending GPS", panel)
        self._btn_clear_sel.setObjectName("btn_clear")
        self._btn_clear_sel.setEnabled(False)
        self._btn_clear_sel.clicked.connect(self._clear_pending_gps_selected)
        self._btn_clear_sel.setToolTip("Remove unsaved GPS from selected photos (Delete)")
        vcol.addWidget(self._btn_clear_sel)

        r1.addWidget(gps_box, stretch=1)
        r1.addLayout(vcol)
        lay.addLayout(r1)

        # Row 2: Auto-tag
        r2 = QHBoxLayout()
        auto_box = QGroupBox("Auto-tag by shooting time", panel)
        al = QHBoxLayout(auto_box)
        al.addWidget(QLabel("Max gap:"))
        self._spin_gap = QDoubleSpinBox(panel)
        self._spin_gap.setRange(0.0, 60.0)
        self._spin_gap.setSingleStep(0.5)
        self._spin_gap.setValue(3.0)
        self._spin_gap.setSuffix(" min")
        al.addWidget(self._spin_gap)
        al.addStretch()

        self._btn_auto = QPushButton("⚡  Auto-tag Photos", panel)
        self._btn_auto.setObjectName("btn_auto")
        self._btn_auto.setEnabled(False)
        self._btn_auto.clicked.connect(self._auto_tag)
        self._btn_auto.setToolTip(
            "Copy GPS from a geotagged photo to any un-tagged photo\n"
            "within the time gap. Shows a preview before applying."
        )
        r2.addWidget(auto_box, stretch=1)
        r2.addWidget(self._btn_auto)
        lay.addLayout(r2)

        # Row 3: Save options
        r3 = QHBoxLayout()
        opts_box = QGroupBox("Save Options", panel)
        ol = QHBoxLayout(opts_box)

        self._chk_norm_dates = QCheckBox("Normalize dates → Date Taken", opts_box)
        self._chk_norm_dates.setChecked(True)
        self._chk_norm_dates.setToolTip(
            "Set ModifyDate, CreateDate and filesystem timestamp = DateTimeOriginal"
        )
        ol.addWidget(self._chk_norm_dates)

        sep = QFrame(opts_box)
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #2d3748;")
        ol.addWidget(sep)

        self._chk_rename = QCheckBox("Rename  YYYYMMDD HHMMSS", opts_box)
        self._chk_rename.toggled.connect(self._on_rename_toggled)
        ol.addWidget(self._chk_rename)

        self._chk_append_orig = QCheckBox("+ original name", opts_box)
        self._chk_append_orig.setEnabled(False)
        self._chk_append_orig.setToolTip("e.g.  20240715 134522 IMG_4823.JPG")
        ol.addWidget(self._chk_append_orig)
        ol.addStretch()

        r3.addWidget(opts_box, stretch=1)
        lay.addLayout(r3)

        # Row 4: Info + Save
        r4 = QHBoxLayout()
        self._lbl_sel_info = QLabel("No photos loaded", panel)
        self._lbl_sel_info.setObjectName("lbl_dim")
        r4.addWidget(self._lbl_sel_info, stretch=1)

        self._btn_save = QPushButton("💾  Save All Changes", panel)
        self._btn_save.setObjectName("btn_primary")
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._save_changes)
        self._btn_save.setToolTip(
            "Write GPS + date changes to disk (Ctrl+S).\n"
            "All original metadata is preserved — only touched tags change.\n"
            "Uses a single ExifTool process for all files (fast)."
        )
        r4.addWidget(self._btn_save)
        lay.addLayout(r4)

        return panel

    def _build_statusbar(self):
        sb = QStatusBar(self)
        self.setStatusBar(sb)
        self._lbl_status = QLabel("Ready")
        sb.addWidget(self._lbl_status, 1)
        hint = QLabel(
            "Ctrl+O open  |  Ctrl+A select all  |  Ctrl+↵ assign GPS  |  Del clear pending  |  Ctrl+S save"
        )
        hint.setObjectName("lbl_dim")
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
        _act("Ctrl+Return", self._assign_gps)
        _act("Ctrl+S",      self._save_changes)
        _act("Delete",      self._clear_pending_gps_selected)
        _act("Backspace",   self._clear_pending_gps_selected)

    # =========================================================================
    # Settings persistence
    # =========================================================================

    def _restore_settings(self):
        """Restore window geometry and user preferences from last session."""
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
                self._splitter_h.setSizes([530, 910])

        gap = self._settings.value(SETTINGS_GAP, 3.0, type=float)
        self._spin_gap.setValue(gap)

        norm = self._settings.value(SETTINGS_NORM_DATES, True, type=bool)
        self._chk_norm_dates.setChecked(norm)

        rename = self._settings.value(SETTINGS_RENAME, False, type=bool)
        self._chk_rename.setChecked(rename)

        append = self._settings.value(SETTINGS_APPEND, False, type=bool)
        self._chk_append_orig.setChecked(append)
        self._chk_append_orig.setEnabled(rename)

    def _save_settings(self):
        """Persist window geometry and user preferences."""
        self._settings.setValue(SETTINGS_GEOMETRY,   self.saveGeometry())
        self._settings.setValue(SETTINGS_SPLITTER_H, self._splitter_h.saveState())
        self._settings.setValue(SETTINGS_GAP,        self._spin_gap.value())
        self._settings.setValue(SETTINGS_NORM_DATES, self._chk_norm_dates.isChecked())
        self._settings.setValue(SETTINGS_RENAME,     self._chk_rename.isChecked())
        self._settings.setValue(SETTINGS_APPEND,     self._chk_append_orig.isChecked())

    # =========================================================================
    # Folder loading
    # =========================================================================

    def _open_folder(self):
        last = self._settings.value(SETTINGS_LAST_DIR,
                                    str(Path.home() / "Pictures"), type=str)
        folder_str = QFileDialog.getExistingDirectory(
            self, "Select Photo Folder", last,
            QFileDialog.Option.ShowDirsOnly,
        )
        if not folder_str:
            return
        folder = Path(folder_str)
        self._settings.setValue(SETTINGS_LAST_DIR, folder_str)

        for t in [self._scan_thread, self._thumb_thread]:
            if t and t.isRunning():
                if hasattr(t, "cancel"):
                    t.cancel()
                t.wait(3000)

        self._grid.clear()
        self._grid.set_base_folder(folder)
        self._all_items.clear()
        self._selected_gps = None
        self._info_bar.set_item(None)
        self._lbl_folder.setText(f"  {folder_str}")
        self._lbl_pending.setVisible(False)
        self._update_action_states()
        self._map.clear_picker()

        self._status(f"Scanning {folder_str}…")
        self._progress.setRange(0, 0)
        self._progress.setVisible(True)

        self._scan_thread = ScanThread(folder, self)
        self._scan_thread.item_ready.connect(self._on_item_ready)
        self._scan_thread.scan_done.connect(self._on_scan_done)
        self._scan_thread.error.connect(self._on_scan_error)
        self._scan_thread.start()

    @Slot(object)
    def _on_item_ready(self, item: PhotoItem):
        self._all_items.append(item)
        self._grid.add_item(item)
        if len(self._all_items) % 25 == 0:
            self._status(f"Loading…  {len(self._all_items)} photos found")
        self._ui_update_timer.start()

    @Slot(int)
    def _on_scan_done(self, total: int):
        self._progress.setVisible(False)
        n_miss = sum(1 for i in self._all_items if not i.has_gps)
        self._status(
            f"Loaded {total} photos — {n_miss} missing GPS — generating thumbnails…"
        )
        self._update_action_states()
        self._map.show_photo_markers(self._all_items)

        self._thumb_thread = ThumbnailThread(list(self._all_items), self)
        self._thumb_thread.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._thumb_thread.all_done.connect(self._on_thumbnails_done)
        self._thumb_thread.start()

    @Slot(str)
    def _on_scan_error(self, msg: str):
        self._progress.setVisible(False)
        QMessageBox.critical(self, "Scan Error", msg)
        self._status("Scan error — see dialog.")

    @Slot(object)
    def _on_thumbnail_ready(self, item: PhotoItem):
        self._grid.refresh_cell(item)
        # Update info bar if this is the currently previewed item
        if self._info_bar._item is item:
            self._info_bar.refresh()

    @Slot()
    def _on_thumbnails_done(self):
        n_miss = sum(1 for i in self._all_items if not i.has_gps)
        self._status(
            f"✓ Ready — {len(self._all_items)} photos, {n_miss} missing GPS"
        )

    # =========================================================================
    # Selection
    # =========================================================================

    @Slot(list)
    def _on_selection_changed(self, selected: list[PhotoItem]):
        n     = len(selected)
        total = len(self._all_items)
        gps_hint = (
            f"  |  Map: {self._selected_gps[0]:.6f}, {self._selected_gps[1]:.6f}"
            if self._selected_gps else ""
        )
        self._lbl_sel_info.setText(f"{n} of {total} selected{gps_hint}")
        self._update_action_states()

        # Show/update info bar for single selection
        self._info_bar.set_item(selected[0] if n == 1 else None)

        # Single selection with GPS → fly map there
        if n == 1:
            item = selected[0]
            g = item.effective_gps
            if g:
                self._map.fly_to(*g)
                self._map.set_picker(*g)
                self._selected_gps = g
                self._lbl_gps.setText(f"  {g[0]:.6f},  {g[1]:.6f}")

    @Slot(object)
    def _on_photo_activated(self, item: PhotoItem):
        """Double-click: fly map to the photo's GPS location."""
        g = item.effective_gps
        if g:
            self._map.fly_to(*g, zoom=15)

    # =========================================================================
    # Map GPS pick
    # =========================================================================

    @Slot(float, float, str)
    def _on_location_picked(self, lat: float, lon: float, label: str):
        self._selected_gps = (lat, lon)
        self._lbl_gps.setText(f"  {lat:.6f},  {lon:.6f}")
        if label:
            self._lbl_gps.setToolTip(label)
        self._update_action_states()
        selected = self._grid.selected_items()
        self._lbl_sel_info.setText(
            f"{len(selected)} of {len(self._all_items)} selected"
            f"  |  Map: {lat:.6f}, {lon:.6f}"
        )

    # =========================================================================
    # Assign GPS
    # =========================================================================

    def _assign_gps(self):
        if not self._selected_gps:
            self._status("Pick a location on the map first.")
            return
        selected = self._grid.selected_items()
        if not selected:
            self._status("Select photos in the grid first.")
            return

        lat, lon = self._selected_gps
        for item in selected:
            item.pending.gps = (lat, lon)

        self._grid.refresh_all()
        self._info_bar.refresh()
        self._map.show_photo_markers(self._all_items)
        self._update_action_states()
        self._status(
            f"📍 GPS {lat:.6f}, {lon:.6f} staged for {len(selected)} photo(s) — "
            "click 'Save All Changes' to write."
        )

    # =========================================================================
    # Clear pending GPS
    # =========================================================================

    def _clear_pending_gps_selected(self):
        selected = [i for i in self._grid.selected_items() if i.pending.gps]
        if not selected:
            return
        for item in selected:
            item.pending.gps = None
        self._grid.refresh_all()
        self._info_bar.refresh()
        self._map.show_photo_markers(self._all_items)
        self._update_action_states()
        self._status(f"Cleared pending GPS from {len(selected)} photo(s).")

    @Slot(object)
    def _clear_pending_gps_item(self, item: PhotoItem):
        """Called from right-click context menu on a single cell."""
        if item.pending.gps:
            item.pending.gps = None
            self._grid.refresh_cell(item)
            self._info_bar.refresh()
            self._map.show_photo_markers(self._all_items)
            self._update_action_states()
            self._status(f"Cleared pending GPS from {item.display_name}.")

    # =========================================================================
    # Show in Explorer
    # =========================================================================

    @Slot(object)
    def _show_in_explorer(self, item: PhotoItem):
        try:
            subprocess.Popen(["explorer", "/select,", str(item.display_path.resolve())])
        except Exception as exc:
            log.warning("Explorer open failed: %s", exc)

    # =========================================================================
    # Auto-tag
    # =========================================================================

    def _auto_tag(self):
        gap     = self._spin_gap.value()
        preview = preview_auto_tag(self._all_items, gap)

        if not preview:
            QMessageBox.information(
                self, "Auto-tag",
                f"No un-tagged photos found within {gap:.1f} minutes of a geotagged photo.\n\n"
                "Assign GPS to at least one photo first, then try again."
            )
            return

        lines = [
            f"Auto-tag will stage GPS on <b>{len(preview)}</b> photo(s) "
            f"within <b>{gap:.1f} min</b> of a geotagged photo.<br><br>"
            "Sample matches:<br>",
        ]
        for item, gps, anchor in preview[:6]:
            lines.append(
                f"&nbsp;&nbsp;• {item.display_name} → "
                f"{gps[0]:.5f}, {gps[1]:.5f}  (from {anchor})<br>"
            )
        if len(preview) > 6:
            lines.append(f"<br>&nbsp;&nbsp;… and {len(preview) - 6} more.")

        reply = QMessageBox.question(
            self, "Confirm Auto-tag", "".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        tagged = auto_tag_by_time(self._all_items, gap)
        self._grid.refresh_all()
        self._info_bar.refresh()
        self._map.show_photo_markers(self._all_items)
        self._update_action_states()
        self._status(
            f"⚡ Auto-tagged {len(tagged)} photo(s) — click 'Save All Changes' to write."
        )

    # =========================================================================
    # Save
    # =========================================================================

    def _save_changes(self):
        to_save = [i for i in self._all_items if i.pending.gps is not None]
        if not to_save:
            QMessageBox.information(
                self, "Nothing to Save",
                "No photos have pending GPS changes.\n\n"
                "Assign GPS to photos first, then click Save."
            )
            return

        norm_dates  = self._chk_norm_dates.isChecked()
        do_rename   = self._chk_rename.isChecked()
        append_orig = self._chk_append_orig.isChecked()
        n_files     = sum(len(i.all_paths) for i in to_save)

        bullet = lambda b, t: f"• {t}<br>" if b else ""   # noqa: E731
        body = (
            f"About to update <b>{len(to_save)}</b> photo(s) "
            f"(<b>{n_files}</b> physical files):<br><br>"
            "• Write GPS coordinates to EXIF<br>"
            + bullet(norm_dates, "Normalize all date fields → DateTimeOriginal")
            + bullet(do_rename,
                     f"Rename to  YYYYMMDD HHMMSS{' + original name' if append_orig else ''}.ext")
            + "<br><b>All other metadata is preserved.</b><br>"
            "Uses a single ExifTool process — fast even for hundreds of files.<br>"
            "No backup files are created (overwrites in-place)."
        )
        reply = QMessageBox.question(
            self, "Confirm Save", body,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._set_busy(True)
        self._progress.setRange(0, len(to_save))
        self._progress.setValue(0)
        self._progress.setVisible(True)

        self._save_thread = SaveThread(to_save, norm_dates, do_rename, append_orig, self)
        self._save_thread.progress.connect(self._on_save_progress)
        self._save_thread.done.connect(self._on_save_done)
        self._save_thread.error.connect(self._on_save_error)
        self._save_thread.start()

    @Slot(int, int)
    def _on_save_progress(self, n: int, total: int):
        self._progress.setValue(n)
        self._status(f"Saving…  {n} / {total}")

    @Slot(list)
    def _on_save_done(self, warnings: list[str]):
        self._progress.setVisible(False)
        self._grid.refresh_all()
        self._info_bar.refresh()
        self._map.show_photo_markers(self._all_items)
        self._set_busy(False)   # also calls _update_action_states

        n_ok   = sum(1 for i in self._all_items if i.has_gps)
        n_miss = len(self._all_items) - n_ok

        if warnings:
            WarningsDialog(warnings, self).exec()
            self._status(f"Saved with {len(warnings)} warning(s). Check the log.")
        else:
            self._status(
                f"✓ All changes written — {n_ok} geotagged, {n_miss} still missing GPS."
            )
            QMessageBox.information(
                self, "Save Complete",
                f"✓ Changes written successfully.\n\n"
                f"• {n_ok} photos now have GPS\n"
                f"• {n_miss} photos still missing GPS",
            )

    @Slot(str)
    def _on_save_error(self, msg: str):
        self._progress.setVisible(False)
        self._set_busy(False)
        QMessageBox.critical(self, "Save Error", msg)
        self._status("Save failed — see dialog.")

    # =========================================================================
    # Helpers
    # =========================================================================

    def _on_rename_toggled(self, checked: bool):
        self._chk_append_orig.setEnabled(checked)

    def _update_action_states(self):
        has_items     = bool(self._all_items)
        selected      = self._grid.selected_items()
        has_sel       = bool(selected)
        has_map_gps   = self._selected_gps is not None
        n_pending     = sum(1 for i in self._all_items if i.pending.gps)
        has_pending   = n_pending > 0
        has_anchors   = any(i.effective_gps for i in self._all_items)
        sel_pending   = any(i.pending.gps for i in selected)

        self._btn_sel_all.setEnabled(has_items)
        self._btn_sel_none.setEnabled(has_items)
        self._btn_sel_missing.setEnabled(has_items)
        self._btn_assign.setEnabled(has_sel and has_map_gps)
        self._btn_clear_sel.setEnabled(has_sel and sel_pending)
        self._btn_auto.setEnabled(has_items and has_anchors)
        self._btn_save.setEnabled(has_pending)

        if n_pending:
            self._lbl_pending.setText(f"  ● {n_pending} pending  ")
            self._lbl_pending.setVisible(True)
        else:
            self._lbl_pending.setVisible(False)

    def _set_busy(self, busy: bool):
        for w in [self._btn_open, self._btn_assign, self._btn_auto,
                  self._btn_save, self._btn_clear_sel]:
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
            "Then either:\n"
            "  • Rename it to exiftool.exe and place it in the project folder\n"
            "  • Or add it to your system PATH\n\n"
            "Without ExifTool, metadata cannot be read or written.",
        )

    def closeEvent(self, event):
        self._save_settings()
        for t in [self._scan_thread, self._thumb_thread, self._save_thread]:
            if t and t.isRunning():
                if hasattr(t, "cancel"):
                    t.cancel()
                t.wait(3000)
        super().closeEvent(event)
