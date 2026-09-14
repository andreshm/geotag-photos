"""track_match_dialog.py — Cyber-Dark Dialog for matching photos with OwnTracks Server / GPS Track Files."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import logging
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QButtonGroup, QComboBox,
    QFrame, QWidget, QMessageBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QCheckBox,
    QSpinBox, QSlider, QSplitter, QProgressBar,
)

from resources.theme import Colors, STYLE_MODERN_CYBER
from .photo_item import PhotoItem
from .track_service import (
    TrackPoint,
    TrackParser,
    OwnTracksClient,
    TrackMatcher,
    TrackMatchResult,
    SETTINGS_OWNTRACKS_URL,
    SETTINGS_OWNTRACKS_USER,
    SETTINGS_OWNTRACKS_DEVICE,
    SETTINGS_OWNTRACKS_AUTH_TYPE,
    SETTINGS_OWNTRACKS_AUTH_USER,
    SETTINGS_OWNTRACKS_AUTH_PASS,
    SETTINGS_TRACK_OFFSET_SECS,
    SETTINGS_TRACK_TOLERANCE_MIN,
    SETTINGS_TRACK_INTERPOLATE,
    SETTINGS_TRACK_MAX_ACCURACY,
)

log = logging.getLogger(__name__)


class TrackMatchDialog(QDialog):
    """Dialog to connect to OwnTracks server or load track files and match photos by Date Taken."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        photos: Optional[Sequence[PhotoItem]] = None,
        map_widget = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("🛰️ Match Photos with OwnTracks / GPS Track")
        self.resize(880, 680)
        self.setMinimumSize(780, 580)
        self.setStyleSheet(STYLE_MODERN_CYBER)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        self._photos: list[PhotoItem] = [p for p in (photos or []) if p.date_taken is not None]
        self._map_widget = map_widget
        self._settings = QSettings("GeoTag", "GeoTagStudioPRO")

        self._track_points: list[TrackPoint] = []
        self._last_match_result: Optional[TrackMatchResult] = None
        self._applied_count: int = 0

        self._build_ui()
        self._load_settings()
        self._inspect_photos_date_range()

    @property
    def applied_count(self) -> int:
        return self._applied_count

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # ── Header ───────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        lbl_icon = QLabel("🛰️", self)
        lbl_icon.setStyleSheet("font-size: 26px;")
        hdr.addWidget(lbl_icon)

        hdr_v = QVBoxLayout()
        hdr_v.setSpacing(2)
        lbl_title = QLabel("GPS Track & OwnTracks Geotagger", self)
        lbl_title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {Colors.TEXT_PRIMARY};")
        lbl_sub = QLabel(
            "Correlate photo 'Date Taken' timestamps against your OwnTracks server or recorded GPS tracks.",
            self
        )
        lbl_sub.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_MUTED};")
        hdr_v.addWidget(lbl_title)
        hdr_v.addWidget(lbl_sub)
        hdr.addLayout(hdr_v, stretch=1)

        # Photo count badge
        self._lbl_photo_count_badge = QLabel(f"📷 {len(self._photos)} Photo(s) Loaded", self)
        self._lbl_photo_count_badge.setStyleSheet(
            f"background: {Colors.BG_CARD}; border: 1px solid {Colors.BORDER_CARD}; "
            f"color: {Colors.CYAN_LIGHT}; border-radius: 6px; padding: 4px 10px; font-size: 11px; font-weight: bold;"
        )
        hdr.addWidget(self._lbl_photo_count_badge)

        root.addLayout(hdr)

        # ── Main Tabs: Server Connection vs File Import ───────────────────────
        self._tabs = QTabWidget(self)
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {Colors.BORDER_DEFAULT};
                background: {Colors.BG_CARD};
                border-radius: 8px;
            }}
            QTabBar::tab {{
                background: {Colors.BG_PANEL};
                color: {Colors.TEXT_SECONDARY};
                padding: 8px 16px;
                font-size: 11px;
                font-weight: bold;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background: {Colors.BG_CARD};
                color: {Colors.CYAN_LIGHT};
                border-bottom: 2px solid {Colors.CYAN};
            }}
        """)

        self._tab_server = QWidget()
        self._tab_file = QWidget()

        self._build_server_tab(self._tab_server)
        self._build_file_tab(self._tab_file)

        self._tabs.addTab(self._tab_server, "🌐  Connect OwnTracks Server")
        self._tabs.addTab(self._tab_file, "📂  Import Track File (GPX / REC / JSON)")
        root.addWidget(self._tabs)

        # ── Time Alignment & Tolerance Controls Card ──────────────────────────
        align_card = QFrame(self)
        align_card.setStyleSheet(
            f"QFrame {{ background: {Colors.BG_PANEL}; border: 1px solid {Colors.BORDER_DEFAULT}; border-radius: 8px; }}"
        )
        al_lay = QVBoxLayout(align_card)
        al_lay.setContentsMargins(14, 10, 14, 10)
        al_lay.setSpacing(8)

        al_title = QLabel("⏱️  Time Synchronization & Interpolation Settings", align_card)
        al_title.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {Colors.TEXT_PRIMARY};")
        al_lay.addWidget(al_title)

        row_ctrls = QHBoxLayout()
        row_ctrls.setSpacing(12)

        # Camera Timezone Preset
        lbl_tz = QLabel("Camera Timezone:", align_card)
        lbl_tz.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._combo_tz = QComboBox(align_card)
        self._combo_tz.setFixedWidth(160)
        self._populate_timezone_presets()
        self._combo_tz.currentIndexChanged.connect(self._on_tz_preset_changed)
        row_ctrls.addWidget(lbl_tz)
        row_ctrls.addWidget(self._combo_tz)

        # Fine Shift Seconds
        lbl_fine = QLabel("Fine Drift (±sec):", align_card)
        lbl_fine.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._spin_fine_drift = QSpinBox(align_card)
        self._spin_fine_drift.setRange(-86400, 86400)
        self._spin_fine_drift.setSingleStep(5)
        self._spin_fine_drift.setValue(0)
        self._spin_fine_drift.setSuffix(" s")
        self._spin_fine_drift.setFixedWidth(80)
        self._spin_fine_drift.valueChanged.connect(self._on_match_params_changed)
        row_ctrls.addWidget(lbl_fine)
        row_ctrls.addWidget(self._spin_fine_drift)

        # Tolerance
        lbl_tol = QLabel("Max Time Gap:", align_card)
        lbl_tol.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._combo_tolerance = QComboBox(align_card)
        self._combo_tolerance.setFixedWidth(110)
        self._combo_tolerance.addItem("1 minute", 60)
        self._combo_tolerance.addItem("3 minutes", 180)
        self._combo_tolerance.addItem("5 minutes", 300)
        self._combo_tolerance.addItem("10 minutes", 600)
        self._combo_tolerance.addItem("15 minutes", 900)
        self._combo_tolerance.addItem("30 minutes", 1800)
        self._combo_tolerance.addItem("60 minutes", 3600)
        self._combo_tolerance.setCurrentIndex(3)  # 10 min default
        self._combo_tolerance.currentIndexChanged.connect(self._on_match_params_changed)
        row_ctrls.addWidget(lbl_tol)
        row_ctrls.addWidget(self._combo_tolerance)

        # Interpolation Checkbox
        self._chk_interpolate = QCheckBox("Interpolate", align_card)
        self._chk_interpolate.setChecked(True)
        self._chk_interpolate.setToolTip("Linearly interpolate latitude, longitude, and elevation between surrounding GPS points")
        self._chk_interpolate.toggled.connect(self._on_match_params_changed)
        row_ctrls.addWidget(self._chk_interpolate)

        # Max Accuracy Filter
        lbl_acc = QLabel("Accuracy:", align_card)
        lbl_acc.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._combo_accuracy = QComboBox(align_card)
        self._combo_accuracy.setFixedWidth(100)
        self._combo_accuracy.addItem("Any", 0)
        self._combo_accuracy.addItem("≤ 25 m", 25)
        self._combo_accuracy.addItem("≤ 50 m", 50)
        self._combo_accuracy.addItem("≤ 100 m", 100)
        self._combo_accuracy.currentIndexChanged.connect(self._on_match_params_changed)
        row_ctrls.addWidget(lbl_acc)
        row_ctrls.addWidget(self._combo_accuracy)

        row_ctrls.addStretch()
        al_lay.addLayout(row_ctrls)

        root.addWidget(align_card)

        # ── Results Banner / Stat Line ───────────────────────────────────────
        self._banner_match = QLabel("⏳ No track loaded yet. Connect to OwnTracks or import a track file above.", self)
        self._banner_match.setStyleSheet(
            f"background: {Colors.BG_CARD}; border: 1px solid {Colors.BORDER_CARD}; "
            f"border-radius: 6px; padding: 6px 12px; font-size: 11.5px; color: {Colors.TEXT_SECONDARY};"
        )
        root.addWidget(self._banner_match)

        # ── Preview Table ─────────────────────────────────────────────────────
        self._table = QTableWidget(self)
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels([
            "Photo Filename", "Photo Date Taken", "Adjusted Time (UTC)", "Matched Lat / Lon", "Elevation", "Delta", "Type"
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        root.addWidget(self._table, stretch=1)

        # ── Bottom Action Buttons ─────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._btn_view_map = QPushButton("🗺️  View Route on Map", self)
        self._btn_view_map.setEnabled(False)
        self._btn_view_map.clicked.connect(self._view_route_on_map)
        btn_row.addWidget(self._btn_view_map)

        btn_row.addStretch()

        btn_cancel = QPushButton("Cancel", self)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        self._btn_stage_gps = QPushButton("📍  Stage Matched GPS", self)
        self._btn_stage_gps.setObjectName("btn_primary")
        self._btn_stage_gps.setEnabled(False)
        self._btn_stage_gps.clicked.connect(self._apply_and_stage_gps)
        btn_row.addWidget(self._btn_stage_gps)

        root.addLayout(btn_row)

    # =========================================================================
    # Tab 1: OwnTracks Server
    # =========================================================================

    def _build_server_tab(self, parent: QWidget):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        desc = QLabel(
            "Connect directly to your OwnTracks Recorder API (or custom endpoint) to download location logs.",
            parent
        )
        desc.setStyleSheet(f"font-size: 11px; color: {Colors.CYAN_LIGHT};")
        lay.addWidget(desc)

        # Row 1: Server URL
        r_url = QHBoxLayout()
        lbl_url = QLabel("Server URL:", parent)
        lbl_url.setFixedWidth(80)
        lbl_url.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._txt_server_url = QLineEdit(parent)
        self._txt_server_url.setPlaceholderText("http://localhost:8083 or https://owntracks.example.com/recorder")
        r_url.addWidget(lbl_url)
        r_url.addWidget(self._txt_server_url, stretch=1)
        lay.addLayout(r_url)

        # Row 2: User & Device
        r_ud = QHBoxLayout()
        lbl_u = QLabel("User:", parent)
        lbl_u.setFixedWidth(80)
        lbl_u.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._txt_user = QLineEdit(parent)
        self._txt_user.setPlaceholderText("e.g. john")

        lbl_d = QLabel("Device:", parent)
        lbl_d.setFixedWidth(50)
        lbl_d.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._txt_device = QLineEdit(parent)
        self._txt_device.setPlaceholderText("e.g. phone")

        r_ud.addWidget(lbl_u)
        r_ud.addWidget(self._txt_user, stretch=1)
        r_ud.addWidget(lbl_d)
        r_ud.addWidget(self._txt_device, stretch=1)
        lay.addLayout(r_ud)

        # Row 3: Auth
        r_auth = QHBoxLayout()
        lbl_auth = QLabel("Authentication:", parent)
        lbl_auth.setFixedWidth(80)
        lbl_auth.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._combo_auth = QComboBox(parent)
        self._combo_auth.addItems(["No Authentication", "HTTP Basic Auth", "Bearer Token / API Key"])
        self._combo_auth.currentIndexChanged.connect(self._on_auth_type_changed)

        self._txt_auth_user = QLineEdit(parent)
        self._txt_auth_user.setPlaceholderText("Username")
        self._txt_auth_user.setVisible(False)

        self._txt_auth_pass = QLineEdit(parent)
        self._txt_auth_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self._txt_auth_pass.setPlaceholderText("Password / Token")
        self._txt_auth_pass.setVisible(False)

        self._btn_show_pass = QPushButton("👁", parent)
        self._btn_show_pass.setFixedWidth(28)
        self._btn_show_pass.setVisible(False)
        self._btn_show_pass.clicked.connect(lambda: self._toggle_echo(self._txt_auth_pass))

        r_auth.addWidget(lbl_auth)
        r_auth.addWidget(self._combo_auth)
        r_auth.addWidget(self._txt_auth_user, stretch=1)
        r_auth.addWidget(self._txt_auth_pass, stretch=1)
        r_auth.addWidget(self._btn_show_pass)
        lay.addLayout(r_auth)

        # Row 4: Photo date range info & Fetch CTA
        r_fetch = QHBoxLayout()
        self._lbl_server_date_info = QLabel("Auto query range: (calculated from photos)", parent)
        self._lbl_server_date_info.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 10.5px;")

        self._chk_remember_creds = QCheckBox("💾 Remember Credentials locally (in OS Registry)", parent)
        self._chk_remember_creds.setChecked(True)
        self._chk_remember_creds.setStyleSheet("font-size: 11px;")

        self._btn_fetch_server = QPushButton("🔌  Fetch OwnTracks Track", parent)
        self._btn_fetch_server.setObjectName("btn_action_cyan")
        self._btn_fetch_server.clicked.connect(self._fetch_server_track)

        r_fetch.addWidget(self._chk_remember_creds)
        r_fetch.addStretch()
        r_fetch.addWidget(self._btn_fetch_server)
        lay.addLayout(r_fetch)

        self._lbl_server_status = QLabel("", parent)
        self._lbl_server_status.setStyleSheet("font-size: 11px; font-weight: bold;")
        lay.addWidget(self._lbl_server_status)

    def _on_auth_type_changed(self, idx: int):
        # 0: None, 1: Basic, 2: Bearer
        if idx == 0:
            self._txt_auth_user.setVisible(False)
            self._txt_auth_pass.setVisible(False)
            self._btn_show_pass.setVisible(False)
        elif idx == 1:
            self._txt_auth_user.setVisible(True)
            self._txt_auth_pass.setVisible(True)
            self._btn_show_pass.setVisible(True)
            self._txt_auth_pass.setPlaceholderText("Password")
        elif idx == 2:
            self._txt_auth_user.setVisible(False)
            self._txt_auth_pass.setVisible(True)
            self._btn_show_pass.setVisible(True)
            self._txt_auth_pass.setPlaceholderText("Bearer Token / Key")

    def _toggle_echo(self, line_edit: QLineEdit):
        if line_edit.echoMode() == QLineEdit.EchoMode.Password:
            line_edit.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            line_edit.setEchoMode(QLineEdit.EchoMode.Password)

    # =========================================================================
    # Tab 2: File Import
    # =========================================================================

    def _build_file_tab(self, parent: QWidget):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        desc = QLabel(
            "Upload or drag & drop OwnTracks export files (.rec, .json), standard GPX files (.gpx), or GeoJSON.",
            parent
        )
        desc.setStyleSheet(f"font-size: 11px; color: {Colors.EMERALD_LIGHT};")
        lay.addWidget(desc)

        r_file = QHBoxLayout()
        lbl_file = QLabel("Track File:", parent)
        lbl_file.setFixedWidth(80)
        lbl_file.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._txt_file_path = QLineEdit(parent)
        self._txt_file_path.setPlaceholderText("Path to .gpx, .rec, .json, .geojson track file...")

        btn_browse = QPushButton("📁 Browse...", parent)
        btn_browse.clicked.connect(self._browse_track_file)

        btn_load = QPushButton("⚡ Load File", parent)
        btn_load.setObjectName("btn_action_emerald")
        btn_load.clicked.connect(self._load_selected_file)

        r_file.addWidget(lbl_file)
        r_file.addWidget(self._txt_file_path, stretch=1)
        r_file.addWidget(btn_browse)
        r_file.addWidget(btn_load)
        lay.addLayout(r_file)

        self._lbl_file_info = QLabel("", parent)
        self._lbl_file_info.setStyleSheet("font-size: 11px; font-weight: bold;")
        lay.addWidget(self._lbl_file_info)

    def _browse_track_file(self):
        last_dir = self._settings.value("io/last_track_folder", str(Path.home()), type=str)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select GPS Track / OwnTracks File",
            last_dir,
            "GPS Track Files (*.gpx *.rec *.json *.geojson *.xml);;All Files (*.*)",
        )
        if path:
            self._txt_file_path.setText(path)
            self._settings.setValue("io/last_track_folder", str(Path(path).parent))
            self._load_selected_file()

    def _load_selected_file(self):
        p_str = self._txt_file_path.text().strip()
        if not p_str:
            self._lbl_file_info.setText("✕ Please select a track file first.")
            self._lbl_file_info.setStyleSheet(f"color: {Colors.AMBER_LIGHT};")
            return

        p = Path(p_str)
        if not p.is_file():
            self._lbl_file_info.setText(f"✕ File does not exist: {p_str}")
            self._lbl_file_info.setStyleSheet(f"color: {Colors.ROSE_LIGHT};")
            return

        try:
            points = TrackParser.load_track_file(p)
            if not points:
                self._lbl_file_info.setText(f"✕ No valid GPS timestamped points found in {p.name}")
                self._lbl_file_info.setStyleSheet(f"color: {Colors.ROSE_LIGHT};")
                return

            self._track_points = points
            t_start = points[0].timestamp.strftime("%Y-%m-%d %H:%M")
            t_end = points[-1].timestamp.strftime("%Y-%m-%d %H:%M")
            self._lbl_file_info.setText(
                f"✓ Loaded {len(points):,} GPS fixes from {p.name} ({t_start} → {t_end} UTC)"
            )
            self._lbl_file_info.setStyleSheet(f"color: {Colors.EMERALD_LIGHT};")

            self._run_matching()
        except Exception as exc:
            log.exception("Error loading track file: %s", exc)
            self._lbl_file_info.setText(f"✕ Error parsing file: {exc}")
            self._lbl_file_info.setStyleSheet(f"color: {Colors.ROSE_LIGHT};")

    # =========================================================================
    # Server Track Fetch
    # =========================================================================

    def _fetch_server_track(self):
        url = self._txt_server_url.text().strip()
        user = self._txt_user.text().strip()
        device = self._txt_device.text().strip()

        if not url:
            self._lbl_server_status.setText("✕ Please enter OwnTracks Server URL.")
            self._lbl_server_status.setStyleSheet(f"color: {Colors.AMBER_LIGHT};")
            return

        auth_idx = self._combo_auth.currentIndex()
        auth_type = "none"
        if auth_idx == 1:
            auth_type = "basic"
        elif auth_idx == 2:
            auth_type = "bearer"

        auth_user = self._txt_auth_user.text().strip()
        auth_pass = self._txt_auth_pass.text().strip()

        # Save credentials to QSettings if checked
        if self._chk_remember_creds.isChecked():
            self._settings.setValue(SETTINGS_OWNTRACKS_URL, url)
            self._settings.setValue(SETTINGS_OWNTRACKS_USER, user)
            self._settings.setValue(SETTINGS_OWNTRACKS_DEVICE, device)
            self._settings.setValue(SETTINGS_OWNTRACKS_AUTH_TYPE, auth_type)
            self._settings.setValue(SETTINGS_OWNTRACKS_AUTH_USER, auth_user)
            self._settings.setValue(SETTINGS_OWNTRACKS_AUTH_PASS, auth_pass)
            self._settings.sync()

        # Determine date range from photos with +/- 6 hours buffer
        from_dt: Optional[datetime] = None
        to_dt: Optional[datetime] = None

        if self._photos:
            dts = [p.date_taken for p in self._photos if p.date_taken]
            if dts:
                min_dt = min(dts)
                max_dt = max(dts)
                # Apply timezone offset to photo dates for UTC query
                tz_offset = self._get_current_total_offset_seconds()
                from_dt = (min_dt - timedelta(hours=6, seconds=tz_offset)).replace(tzinfo=timezone.utc)
                to_dt = (max_dt + timedelta(hours=6, seconds=tz_offset)).replace(tzinfo=timezone.utc)

        try:
            self._lbl_server_status.setText("⏳ Connecting to OwnTracks server & querying location logs...")
            self._lbl_server_status.setStyleSheet("color: #38bdf8;")
            self._btn_fetch_server.setEnabled(False)

            points = OwnTracksClient.fetch_locations(
                server_url=url,
                user=user,
                device=device,
                from_dt=from_dt,
                to_dt=to_dt,
                auth_type=auth_type,
                username=auth_user,
                password_or_token=auth_pass,
                timeout=30,
            )

            if not points:
                self._lbl_server_status.setText("✕ Connected, but server returned 0 location points for this date range.")
                self._lbl_server_status.setStyleSheet(f"color: {Colors.AMBER_LIGHT};")
                return

            self._track_points = points
            t_start = points[0].timestamp.strftime("%Y-%m-%d %H:%M")
            t_end = points[-1].timestamp.strftime("%Y-%m-%d %H:%M")
            self._lbl_server_status.setText(
                f"✓ Successfully fetched {len(points):,} GPS fixes ({t_start} → {t_end} UTC)!"
            )
            self._lbl_server_status.setStyleSheet(f"color: {Colors.EMERALD_LIGHT};")

            self._run_matching()
        except Exception as exc:
            log.exception("OwnTracks server fetch error: %s", exc)
            self._lbl_server_status.setText(f"✕ Connection failed: {exc}")
            self._lbl_server_status.setStyleSheet(f"color: {Colors.ROSE_LIGHT};")
        finally:
            self._btn_fetch_server.setEnabled(True)

    # =========================================================================
    # Timezone & Alignment Setup
    # =========================================================================

    def _populate_timezone_presets(self):
        presets = [
            ("UTC+00:00 (GMT/UTC)", 0),
            ("UTC+01:00 (CET/BST)", 3600),
            ("UTC+02:00 (EET/CEST)", 7200),
            ("UTC+03:00 (MSK/EEST)", 10800),
            ("UTC+04:00 (GST)", 14400),
            ("UTC+05:30 (IST)", 19800),
            ("UTC+08:00 (CST/SGT)", 28800),
            ("UTC+09:00 (JST/KST)", 32400),
            ("UTC+10:00 (AEST)", 36000),
            ("UTC+12:00 (NZST)", 43200),
            ("UTC-03:00 (BRT/ART)", -10800),
            ("UTC-04:00 (EDT/AST)", -14400),
            ("UTC-05:00 (EST/CDT)", -18000),
            ("UTC-06:00 (CST/MDT)", -21600),
            ("UTC-07:00 (MST/PDT)", -25200),
            ("UTC-08:00 (PST/AKDT)", -28800),
            ("UTC-10:00 (HST)", -36000),
        ]
        for label, val in presets:
            self._combo_tz.addItem(label, val)

    def _on_tz_preset_changed(self, idx: int):
        self._on_match_params_changed()

    def _get_current_total_offset_seconds(self) -> int:
        tz_offset = int(self._combo_tz.currentData() or 0)
        # Note: If camera was at UTC+2, to align to UTC track we SUBTRACT 2 hours (-7200s)
        camera_offset_to_utc = -tz_offset
        fine_drift = self._spin_fine_drift.value()
        return camera_offset_to_utc + fine_drift

    def _on_match_params_changed(self):
        if self._track_points:
            self._run_matching()

    # =========================================================================
    # Matching Engine Execution
    # =========================================================================

    def _run_matching(self):
        if not self._photos or not self._track_points:
            return

        total_offset = self._get_current_total_offset_seconds()
        tolerance = int(self._combo_tolerance.currentData() or 600)
        use_interp = self._chk_interpolate.isChecked()
        max_acc = float(self._combo_accuracy.currentData() or 0)
        max_acc_val = max_acc if max_acc > 0 else None

        result = TrackMatcher.match_photos(
            photos=self._photos,
            track_points=self._track_points,
            time_offset_seconds=total_offset,
            tolerance_seconds=tolerance,
            use_interpolation=use_interp,
            max_accuracy_meters=max_acc_val,
        )
        self._last_match_result = result
        self._update_results_ui(result)

    def _update_results_ui(self, res: TrackMatchResult):
        # Update Banner
        pct = res.match_percentage
        color = Colors.EMERALD_LIGHT if pct >= 80 else (Colors.AMBER_LIGHT if pct > 0 else Colors.ROSE_LIGHT)
        avg_delta = 0.0
        if res.matched:
            avg_delta = sum(m.delta_seconds for m in res.matched) / len(res.matched)

        self._banner_match.setText(
            f"📊 Match Status: {res.matched_count} / {res.total_photos} photos matched ({pct:.1f}%) | "
            f"Avg Time Gap: {avg_delta:.0f}s | Unmatched: {len(res.unmatched)}"
        )
        self._banner_match.setStyleSheet(
            f"background: {Colors.BG_CARD}; border: 1px solid {color}; "
            f"border-radius: 6px; padding: 6px 12px; font-size: 11.5px; font-weight: bold; color: {color};"
        )

        # Update Buttons
        self._btn_view_map.setEnabled(len(self._track_points) > 0)
        self._btn_stage_gps.setEnabled(res.matched_count > 0)

        # Populate Table
        self._table.setRowCount(0)
        self._table.setSortingEnabled(False)

        # Matched photos first
        row = 0
        matched_dict = {m.photo: m for m in res.matched}

        for photo in self._photos:
            self._table.insertRow(row)
            m = matched_dict.get(photo)

            item_name = QTableWidgetItem(photo.display_name)
            raw_dt_str = photo.date_taken.strftime("%Y-%m-%d %H:%M:%S") if photo.date_taken else "-"
            item_raw_dt = QTableWidgetItem(raw_dt_str)

            if m:
                adj_dt_str = m.adjusted_dt.strftime("%Y-%m-%d %H:%M:%S")
                coords_str = f"{m.lat:.6f}, {m.lon:.6f}"
                alt_str = f"{m.alt:.1f} m" if m.alt is not None else "-"
                delta_str = f"±{m.delta_seconds:.0f}s"
                type_str = "⚡ Interpolated" if m.match_type == "interpolated" else "📍 Nearest Fix"

                item_adj = QTableWidgetItem(adj_dt_str)
                item_coords = QTableWidgetItem(coords_str)
                item_alt = QTableWidgetItem(alt_str)
                item_delta = QTableWidgetItem(delta_str)
                item_type = QTableWidgetItem(type_str)

                # Style matched row
                for it in (item_name, item_raw_dt, item_adj, item_coords, item_alt, item_delta, item_type):
                    it.setForeground(QColor(Colors.TEXT_PRIMARY))
                item_coords.setForeground(QColor(Colors.CYAN_LIGHT))
                item_type.setForeground(QColor(Colors.EMERALD_LIGHT if m.match_type == "interpolated" else Colors.AMBER_LIGHT))
            else:
                item_adj = QTableWidgetItem("-")
                item_coords = QTableWidgetItem("No match in range")
                item_alt = QTableWidgetItem("-")
                item_delta = QTableWidgetItem("-")
                item_type = QTableWidgetItem("✕ Unmatched")

                # Style unmatched row
                for it in (item_name, item_raw_dt, item_adj, item_coords, item_alt, item_delta, item_type):
                    it.setForeground(QColor(Colors.TEXT_MUTED))
                item_type.setForeground(QColor(Colors.ROSE_LIGHT))

            self._table.setItem(row, 0, item_name)
            self._table.setItem(row, 1, item_raw_dt)
            self._table.setItem(row, 2, item_adj)
            self._table.setItem(row, 3, item_coords)
            self._table.setItem(row, 4, item_alt)
            self._table.setItem(row, 5, item_delta)
            self._table.setItem(row, 6, item_type)
            row += 1

    # =========================================================================
    # Action Handlers
    # =========================================================================

    def _view_route_on_map(self):
        if not self._map_widget or not self._track_points:
            return
        pts = [{"lat": p.lat, "lon": p.lon} for p in self._track_points]
        self._map_widget.set_track(pts, color="#a855f7")
        QMessageBox.information(
            self,
            "Route Plotted on Map",
            f"Successfully rendered GPS track with {len(self._track_points):,} points on the main Leaflet map.",
        )

    def _apply_and_stage_gps(self):
        if not self._last_match_result or not self._last_match_result.matched:
            return

        matched = self._last_match_result.matched
        count = 0
        for m in matched:
            m.photo.pending.gps = (m.lat, m.lon)
            count += 1

        self._applied_count = count

        # If map widget is present, also render the track polyline and photo markers
        if self._map_widget:
            if self._track_points:
                pts = [{"lat": p.lat, "lon": p.lon} for p in self._track_points]
                self._map_widget.set_track(pts, color="#a855f7")
            self._map_widget.show_photo_markers([m.photo for m in matched])

        QMessageBox.information(
            self,
            "GPS Coordinates Staged",
            f"Successfully staged pending GPS coordinates for {count} photo(s)!\n\n"
            f"They are now marked with ⏳ in the grid. Click '💾 Save Changes' in the main window when ready to write EXIF metadata.",
        )
        self.accept()

    # =========================================================================
    # Settings & Initialization Helpers
    # =========================================================================

    def _inspect_photos_date_range(self):
        if not self._photos:
            return
        dts = [p.date_taken for p in self._photos if p.date_taken]
        if dts:
            min_dt = min(dts).strftime("%Y-%m-%d %H:%M")
            max_dt = max(dts).strftime("%Y-%m-%d %H:%M")
            self._lbl_server_date_info.setText(f"Photos date span: {min_dt} → {max_dt}")

    def _load_settings(self):
        url = self._settings.value(SETTINGS_OWNTRACKS_URL, "", type=str)
        user = self._settings.value(SETTINGS_OWNTRACKS_USER, "", type=str)
        device = self._settings.value(SETTINGS_OWNTRACKS_DEVICE, "", type=str)
        auth_type = self._settings.value(SETTINGS_OWNTRACKS_AUTH_TYPE, "none", type=str)
        auth_user = self._settings.value(SETTINGS_OWNTRACKS_AUTH_USER, "", type=str)
        auth_pass = self._settings.value(SETTINGS_OWNTRACKS_AUTH_PASS, "", type=str)

        self._txt_server_url.setText(url)
        self._txt_user.setText(user)
        self._txt_device.setText(device)

        if auth_type == "basic":
            self._combo_auth.setCurrentIndex(1)
        elif auth_type == "bearer":
            self._combo_auth.setCurrentIndex(2)
        else:
            self._combo_auth.setCurrentIndex(0)

        self._txt_auth_user.setText(auth_user)
        self._txt_auth_pass.setText(auth_pass)
