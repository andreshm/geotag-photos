"""ai_guesser_dialog.py — Cyber-Dark interactive AI Location Guesser dialog with same-day trip context."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QThread, QObject, QSettings
from PySide6.QtGui import QPixmap, QImage, QPainter, QBrush, QColor, QPen, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QWidget, QProgressBar, QTextEdit,
    QScrollArea, QMessageBox, QSizePolicy
)

from resources.theme import Colors, STYLE_MODERN_CYBER
from .photo_item import PhotoItem
from .photo_manager import generate_thumbnail_image
from .ai_service import (
    AIService,
    AIPredictionResult,
    SETTINGS_AI_PROVIDER,
    SETTINGS_OLLAMA_URL,
    SETTINGS_OLLAMA_MODEL,
    SETTINGS_GEMINI_KEY,
    SETTINGS_GEMINI_MODEL,
    SETTINGS_OPENAI_KEY,
    SETTINGS_OPENAI_MODEL,
)
from .ai_settings_dialog import AISettingsDialog

log = logging.getLogger(__name__)


class _PredictWorker(QObject):
    """Background worker for Vision AI API query."""

    finished = Signal(object)  # AIPredictionResult
    error    = Signal(str)

    def __init__(
        self,
        image_path: Path,
        user_clues: str,
        same_day_anchors: list[dict],
        date_str: str,
        camera_model: str,
        provider: str,
        settings_dict: dict,
        parent=None,
    ):
        super().__init__(parent)
        self._image_path = image_path
        self._user_clues = user_clues
        self._same_day_anchors = same_day_anchors
        self._date_str = date_str
        self._camera_model = camera_model
        self._provider = provider
        self._settings = settings_dict

    def run(self):
        try:
            # 1. Encode image to compact base64 jpeg
            image_b64 = AIService.encode_image_base64(self._image_path)

            # 2. Build contextual prompt
            prompt = AIService.build_prompt(
                user_clues=self._user_clues,
                same_day_anchors=self._same_day_anchors,
                date_str=self._date_str,
                camera_model=self._camera_model,
            )

            # 3. Query selected provider
            if self._provider == "gemini":
                api_key = self._settings.get(SETTINGS_GEMINI_KEY, "")
                model = self._settings.get(SETTINGS_GEMINI_MODEL, "gemini-1.5-flash")
                res = AIService.predict_with_gemini(image_b64, prompt, api_key=api_key, model=model)

            elif self._provider == "openai":
                api_key = self._settings.get(SETTINGS_OPENAI_KEY, "")
                model = self._settings.get(SETTINGS_OPENAI_MODEL, "gpt-4o-mini")
                res = AIService.predict_with_openai(image_b64, prompt, api_key=api_key, model=model)

            else:  # "ollama"
                server_url = self._settings.get(SETTINGS_OLLAMA_URL, "http://localhost:11434")
                model = self._settings.get(SETTINGS_OLLAMA_MODEL, "llama3.2-vision")
                res = AIService.predict_with_ollama(image_b64, prompt, server_url=server_url, model=model)

            self.finished.emit(res)
        except Exception as exc:
            log.error("AI prediction failed: %s", exc, exc_info=True)
            self.error.emit(str(exc))


class AIGuesserDialog(QDialog):
    """Interactive modal dialog to predict photo locations with Vision AI and same-day context."""

    preview_on_map = Signal(float, float)        # (lat, lon)
    apply_gps      = Signal(object, float, float) # (PhotoItem, lat, lon)

    def __init__(
        self,
        item: PhotoItem,
        same_day_anchors: list[dict],
        parent=None,
    ):
        super().__init__(parent)
        self._item = item
        self._same_day_anchors = same_day_anchors
        self._settings = QSettings("GeoTag", "GeoTagStudioPRO")
        self._last_result: Optional[AIPredictionResult] = None
        self._thread: Optional[QThread] = None

        self.setWindowTitle("AI Location Guesser & Vision Geocoding")
        self.setFixedSize(680, 620)
        self.setStyleSheet(STYLE_MODERN_CYBER)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        self._build_ui()
        self._load_active_provider_label()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        # Header Title
        hdr = QHBoxLayout()
        lbl_icon = QLabel("🤖", self)
        lbl_icon.setStyleSheet("font-size: 24px;")
        hdr.addWidget(lbl_icon)

        hdr_v = QVBoxLayout()
        hdr_v.setSpacing(2)
        lbl_title = QLabel("AI Location Guesser", self)
        lbl_title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {Colors.CYAN_LIGHT};")
        self._lbl_active_model = QLabel("Configuring AI Model...", self)
        self._lbl_active_model.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_MUTED};")
        hdr_v.addWidget(lbl_title)
        hdr_v.addWidget(self._lbl_active_model)
        hdr.addLayout(hdr_v)
        hdr.addStretch()

        btn_cfg = QPushButton("⚙️ AI Settings", self)
        btn_cfg.clicked.connect(self._open_settings)
        hdr.addWidget(btn_cfg)
        layout.addLayout(hdr)

        # Main Info Row: Thumbnail (Left) | Context & Clues (Right)
        mid_row = QHBoxLayout()
        mid_row.setSpacing(14)

        # Left: Thumbnail Box
        self._lbl_thumb = QLabel(self)
        self._lbl_thumb.setFixedSize(160, 160)
        self._lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_thumb.setStyleSheet(
            f"background: #070c18; border: 1px solid {Colors.BORDER_CARD}; border-radius: 8px;"
        )
        self._load_thumbnail()
        mid_row.addWidget(self._lbl_thumb)

        # Right: Clues & Same-day Context
        r_box = QVBoxLayout()
        r_box.setSpacing(6)

        # File Details
        lbl_fname = QLabel(f"📄 <b>{self._item.display_name}</b>", self)
        lbl_fname.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-size: 12px;")
        r_box.addWidget(lbl_fname)

        dt_str = self._item.date_taken.strftime("%B %d, %Y at %H:%M:%S") if self._item.date_taken else "Unknown Date"
        lbl_date = QLabel(f"🗓️ Taken: <span style='color:{Colors.CYAN_LIGHT};'>{dt_str}</span>", self)
        lbl_date.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 11px;")
        r_box.addWidget(lbl_date)

        # Same-day Anchor Banner
        self._banner_anchor = QFrame(self)
        self._banner_anchor.setStyleSheet(
            f"background: {Colors.BG_CARD}; border: 1px solid {Colors.CYAN_BG}; border-radius: 6px;"
        )
        b_lay = QHBoxLayout(self._banner_anchor)
        b_lay.setContentsMargins(8, 6, 8, 6)
        
        if self._same_day_anchors:
            first_anchor = self._same_day_anchors[0]
            loc_hint = first_anchor.get("name", "")
            loc_txt = f" near {loc_hint}" if loc_hint else f" ({first_anchor['lat']:.4f}, {first_anchor['lon']:.4f})"
            self._lbl_anchor_text = QLabel(
                f"📍 <b>Same-Day Context:</b> Found <b>{len(self._same_day_anchors)}</b> geotagged photo(s) from this date{loc_txt}. Regional trip context is active!",
                self._banner_anchor
            )
            self._lbl_anchor_text.setStyleSheet(f"color: {Colors.EMERALD_LIGHT}; font-size: 10px;")
        else:
            self._lbl_anchor_text = QLabel(
                "ℹ️ <b>No same-day GPS anchors found:</b> AI will rely strictly on visual features & your hints.",
                self._banner_anchor
            )
            self._lbl_anchor_text.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 10px;")

        self._lbl_anchor_text.setWordWrap(True)
        b_lay.addWidget(self._lbl_anchor_text)
        r_box.addWidget(self._banner_anchor)

        # User Clues Text Box
        lbl_clue_hint = QLabel("💡 Optional Hints or Clues (e.g., 'vacation in Italy', 'near a beach'):", self)
        lbl_clue_hint.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        r_box.addWidget(lbl_clue_hint)

        self._txt_clues = QLineEdit(self)
        self._txt_clues.setPlaceholderText("Type any memory or location clue here...")
        r_box.addWidget(self._txt_clues)

        mid_row.addLayout(r_box, stretch=1)
        layout.addLayout(mid_row)

        # Predict CTA Button
        self._btn_predict = QPushButton("🔮  Ask AI to Guess Location", self)
        self._btn_predict.setFixedHeight(34)
        self._btn_predict.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_predict.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #581c87, stop:1 #9333ea);
                border: 1px solid #c084fc;
                border-radius: 6px;
                color: #ffffff;
                font-size: 12px;
                font-weight: bold;
                padding: 6px 16px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #6b21a8, stop:1 #a855f7);
                border-color: #e9d5ff;
            }}
            QPushButton:disabled {{
                background: #1e1b4b;
                border-color: {Colors.BORDER_DEFAULT};
                color: {Colors.TEXT_MUTED};
            }}
        """)
        self._btn_predict.clicked.connect(self._on_start_prediction)
        layout.addWidget(self._btn_predict)

        # Status / Progress indicator
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)  # Indeterminate pulsing
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._lbl_status = QLabel("", self)
        self._lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_status.setStyleSheet(f"font-size: 11px; color: {Colors.CYAN_LIGHT}; font-style: italic;")
        self._lbl_status.setVisible(False)
        layout.addWidget(self._lbl_status)

        # ── Prediction Results Card ──────────────────────────────────────────
        self._res_card = QFrame(self)
        self._res_card.setStyleSheet(
            f"background: {Colors.BG_PANEL}; border: 1px solid {Colors.CYAN_BG}; border-radius: 8px;"
        )
        self._res_card.setVisible(False)
        res_lay = QVBoxLayout(self._res_card)
        res_lay.setContentsMargins(14, 12, 14, 12)
        res_lay.setSpacing(8)

        # Top Result Row: Location Name + Confidence Pill
        res_top = QHBoxLayout()
        self._lbl_res_name = QLabel("", self._res_card)
        self._lbl_res_name.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Colors.CYAN_LIGHT};")
        self._lbl_res_name.setWordWrap(True)
        res_top.addWidget(self._lbl_res_name, stretch=1)

        self._lbl_res_conf = QLabel("", self._res_card)
        self._lbl_res_conf.setStyleSheet("border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: bold;")
        res_top.addWidget(self._lbl_res_conf)
        res_lay.addLayout(res_top)

        # Coordinates Row
        self._lbl_res_coords = QLabel("", self._res_card)
        self._lbl_res_coords.setStyleSheet(f"font-family: Consolas; font-size: 12px; color: {Colors.EMERALD_LIGHT}; font-weight: bold;")
        res_lay.addWidget(self._lbl_res_coords)

        # Reasoning
        self._lbl_res_reason = QLabel("", self._res_card)
        self._lbl_res_reason.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px; line-height: 1.4;")
        self._lbl_res_reason.setWordWrap(True)
        res_lay.addWidget(self._lbl_res_reason)

        layout.addWidget(self._res_card)

        # Action Buttons Row
        self._act_row = QHBoxLayout()
        self._act_row.addStretch()

        self._btn_preview = QPushButton("📍  Preview on Map", self)
        self._btn_preview.setObjectName("btn_action_cyan")
        self._btn_preview.clicked.connect(self._on_preview_map)
        self._btn_preview.setVisible(False)
        self._act_row.addWidget(self._btn_preview)

        self._btn_apply = QPushButton("✅  Assign GPS to Photo", self)
        self._btn_apply.setObjectName("btn_primary")
        self._btn_apply.clicked.connect(self._on_apply_gps)
        self._btn_apply.setVisible(False)
        self._act_row.addWidget(self._btn_apply)

        layout.addLayout(self._act_row)

    def _load_thumbnail(self):
        try:
            qimg = generate_thumbnail_image(self._item)
            if qimg:
                px = QPixmap.fromImage(qimg).scaled(
                    156, 156,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._lbl_thumb.setPixmap(px)
            else:
                self._lbl_thumb.setText("📷 No Preview")
        except Exception:
            self._lbl_thumb.setText("📷 No Preview")

    def _load_active_provider_label(self):
        prov = self._settings.value(SETTINGS_AI_PROVIDER, "ollama", type=str)
        if prov == "gemini":
            model = self._settings.value(SETTINGS_GEMINI_MODEL, "gemini-1.5-flash", type=str)
            self._lbl_active_model.setText(f"Active Provider: ✨ Google Gemini ({model})")
        elif prov == "openai":
            model = self._settings.value(SETTINGS_OPENAI_MODEL, "gpt-4o-mini", type=str)
            self._lbl_active_model.setText(f"Active Provider: ⚡ OpenAI ({model})")
        else:
            model = self._settings.value(SETTINGS_OLLAMA_MODEL, "llama3.2-vision", type=str)
            self._lbl_active_model.setText(f"Active Provider: 🦙 Local Ollama ({model})")

    def _open_settings(self):
        dlg = AISettingsDialog(self)
        if dlg.exec():
            self._load_active_provider_label()

    def _on_start_prediction(self):
        self._btn_predict.setEnabled(False)
        self._progress.setVisible(True)
        self._lbl_status.setVisible(True)
        self._lbl_status.setText("🤖 Analyzing visual features, landmarks, and trip context...")
        self._res_card.setVisible(False)
        self._btn_preview.setVisible(False)
        self._btn_apply.setVisible(False)

        prov = self._settings.value(SETTINGS_AI_PROVIDER, "ollama", type=str)
        settings_dict = {
            SETTINGS_OLLAMA_URL:   self._settings.value(SETTINGS_OLLAMA_URL, "http://localhost:11434", type=str),
            SETTINGS_OLLAMA_MODEL: self._settings.value(SETTINGS_OLLAMA_MODEL, "llama3.2-vision", type=str),
            SETTINGS_GEMINI_KEY:   self._settings.value(SETTINGS_GEMINI_KEY, "", type=str),
            SETTINGS_GEMINI_MODEL: self._settings.value(SETTINGS_GEMINI_MODEL, "gemini-1.5-flash", type=str),
            SETTINGS_OPENAI_KEY:   self._settings.value(SETTINGS_OPENAI_KEY, "", type=str),
            SETTINGS_OPENAI_MODEL: self._settings.value(SETTINGS_OPENAI_MODEL, "gpt-4o-mini", type=str),
        }

        dt_str = self._item.date_taken.strftime("%Y-%m-%d %H:%M:%S") if self._item.date_taken else ""

        self._thread = QThread(self)
        self._worker = _PredictWorker(
            image_path=self._item.display_path,
            user_clues=self._txt_clues.text().strip(),
            same_day_anchors=self._same_day_anchors,
            date_str=dt_str,
            camera_model=self._item.camera_model,
            provider=prov,
            settings_dict=settings_dict,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_prediction_success)
        self._worker.error.connect(self._on_prediction_error)
        self._thread.start()

    def _on_prediction_success(self, res: AIPredictionResult):
        self._last_result = res
        self._cleanup_thread()

        self._btn_predict.setEnabled(True)
        self._progress.setVisible(False)
        self._lbl_status.setVisible(False)

        # Populate Results Card
        self._lbl_res_name.setText(f"📍 {res.location_name}")
        self._lbl_res_coords.setText(f"Coordinates: {res.latitude:.6f}, {res.longitude:.6f}")

        if res.confidence == "high":
            self._lbl_res_conf.setText("🟢 HIGH CONFIDENCE")
            self._lbl_res_conf.setStyleSheet("background: #064e3b; color: #34d399; border: 1px solid #059669; border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: bold;")
        elif res.confidence == "medium":
            self._lbl_res_conf.setText("🟡 MEDIUM CONFIDENCE")
            self._lbl_res_conf.setStyleSheet("background: #451a03; color: #fbbf24; border: 1px solid #d97706; border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: bold;")
        else:
            self._lbl_res_conf.setText("🔴 LOW CONFIDENCE")
            self._lbl_res_conf.setStyleSheet("background: #4c0519; color: #fda4af; border: 1px solid #e11d48; border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: bold;")

        self._lbl_res_reason.setText(f"<b>Visual & Context Reasoning:</b><br>{res.reasoning}")

        self._res_card.setVisible(True)
        self._btn_preview.setVisible(True)
        self._btn_apply.setVisible(True)

    def _on_prediction_error(self, err_msg: str):
        self._cleanup_thread()
        self._btn_predict.setEnabled(True)
        self._progress.setVisible(False)
        self._lbl_status.setVisible(True)
        self._lbl_status.setText(f"✕ AI Prediction Error: {err_msg}")
        self._lbl_status.setStyleSheet(f"font-size: 11px; color: {Colors.ROSE_LIGHT};")
        QMessageBox.warning(self, "AI Prediction Failed", f"Could not determine location:\n\n{err_msg}")

    def _cleanup_thread(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(500)
            self._thread = None
            self._worker = None

    def _on_preview_map(self):
        if self._last_result:
            self.preview_on_map.emit(self._last_result.latitude, self._last_result.longitude)

    def _on_apply_gps(self):
        if self._last_result:
            self.apply_gps.emit(self._item, self._last_result.latitude, self._last_result.longitude)
            self.accept()
