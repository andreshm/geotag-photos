"""ai_settings_dialog.py — Cyber-Dark AI Configuration dialog for Ollama, Gemini, and OpenAI."""

from __future__ import annotations

import logging
from typing import Optional
import webbrowser

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QButtonGroup, QComboBox,
    QFrame, QWidget, QMessageBox, QTabWidget, QSizePolicy
)
from resources.theme import Colors, STYLE_MODERN_CYBER
from .ai_service import (
    SETTINGS_AI_PROVIDER,
    SETTINGS_OLLAMA_URL,
    SETTINGS_OLLAMA_MODEL,
    SETTINGS_OLLAMA_TIMEOUT,
    SETTINGS_GEMINI_KEY,
    SETTINGS_GEMINI_MODEL,
    SETTINGS_OPENAI_KEY,
    SETTINGS_OPENAI_MODEL,
    SETTINGS_DEEPSEEK_KEY,
    SETTINGS_DEEPSEEK_MODEL,
    AIService,
)

log = logging.getLogger(__name__)


class AISettingsDialog(QDialog):
    """Configuration dialog for AI Location Predictor models and API providers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Vision Geolocation Configuration")
        self.setFixedSize(620, 530)
        self.setStyleSheet(STYLE_MODERN_CYBER)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        self._settings = QSettings("GeoTag", "GeoTagStudioPRO")
        self._build_ui()
        self._load_settings()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        # Header Title
        hdr = QHBoxLayout()
        lbl_icon = QLabel("🤖", self)
        lbl_icon.setStyleSheet("font-size: 24px;")
        hdr.addWidget(lbl_icon)

        hdr_v = QVBoxLayout()
        hdr_v.setSpacing(2)
        lbl_title = QLabel("AI Location Guesser Settings", self)
        lbl_title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {Colors.CYAN_LIGHT};")
        lbl_sub = QLabel("Select and configure the Vision AI model used to guess photo locations.", self)
        lbl_sub.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_MUTED};")
        hdr_v.addWidget(lbl_title)
        hdr_v.addWidget(lbl_sub)
        hdr.addLayout(hdr_v)
        hdr.addStretch()
        layout.addLayout(hdr)

        # Provider Selector Group
        lbl_prov = QLabel("ACTIVE AI PROVIDER:", self)
        lbl_prov.setStyleSheet(f"font-size: 10px; font-weight: bold; color: {Colors.TEXT_MUTED}; letter-spacing: 0.5px;")
        layout.addWidget(lbl_prov)

        prov_row = QHBoxLayout()
        prov_row.setSpacing(10)
        self._rb_ollama = QRadioButton("🦙 Ollama (Local)", self)
        self._rb_gemini = QRadioButton("✨ Gemini", self)
        self._rb_openai = QRadioButton("⚡ OpenAI", self)
        self._rb_deepseek = QRadioButton("🐳 DeepSeek", self)

        self._btn_grp = QButtonGroup(self)
        self._btn_grp.addButton(self._rb_ollama, 0)
        self._btn_grp.addButton(self._rb_gemini, 1)
        self._btn_grp.addButton(self._rb_openai, 2)
        self._btn_grp.addButton(self._rb_deepseek, 3)
        self._btn_grp.idClicked.connect(self._on_provider_changed)

        prov_row.addWidget(self._rb_ollama)
        prov_row.addWidget(self._rb_gemini)
        prov_row.addWidget(self._rb_openai)
        prov_row.addWidget(self._rb_deepseek)
        layout.addLayout(prov_row)

        # Container Card for Provider Settings
        self._card = QFrame(self)
        self._card.setStyleSheet(
            f"background: {Colors.BG_PANEL}; border: 1px solid {Colors.BORDER_DEFAULT}; border-radius: 8px;"
        )
        self._card_lay = QVBoxLayout(self._card)
        self._card_lay.setContentsMargins(16, 14, 16, 14)
        self._card_lay.setSpacing(10)

        # ── Ollama Panel ──
        self._panel_ollama = QWidget(self._card)
        o_lay = QVBoxLayout(self._panel_ollama)
        o_lay.setContentsMargins(0, 0, 0, 0)
        o_lay.setSpacing(8)

        lbl_o_desc = QLabel("Runs 100% locally and privately on your GPU/CPU via Ollama. No API key required.", self._panel_ollama)
        lbl_o_desc.setStyleSheet(f"font-size: 11px; color: {Colors.EMERALD_LIGHT};")
        lbl_o_desc.setWordWrap(True)
        o_lay.addWidget(lbl_o_desc)

        row_url = QHBoxLayout()
        lbl_url = QLabel("Server URL:", self._panel_ollama)
        lbl_url.setFixedWidth(80)
        lbl_url.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._txt_ollama_url = QLineEdit(self._panel_ollama)
        self._txt_ollama_url.setPlaceholderText("http://localhost:11434")
        self._btn_test_ollama = QPushButton("🔄 Refresh Models", self._panel_ollama)
        self._btn_test_ollama.clicked.connect(self._refresh_ollama_models)
        row_url.addWidget(lbl_url)
        row_url.addWidget(self._txt_ollama_url, stretch=1)
        row_url.addWidget(self._btn_test_ollama)
        o_lay.addLayout(row_url)

        row_omodel = QHBoxLayout()
        lbl_omodel = QLabel("Vision Model:", self._panel_ollama)
        lbl_omodel.setFixedWidth(80)
        lbl_omodel.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._combo_ollama_model = QComboBox(self._panel_ollama)
        self._combo_ollama_model.setEditable(True)
        self._combo_ollama_model.addItems(["llama3.2-vision", "llama3.2-vision:11b", "llava", "llava:13b", "minicpm-v", "qwen2.5-vl", "qwen3.5:9b", "bakllava"])
        self._combo_ollama_model.currentTextChanged.connect(self._check_vision_model_compatibility)
        row_omodel.addWidget(lbl_omodel)
        row_omodel.addWidget(self._combo_ollama_model, stretch=1)
        o_lay.addLayout(row_omodel)

        row_timeout = QHBoxLayout()
        lbl_timeout = QLabel("Timeout Limit:", self._panel_ollama)
        lbl_timeout.setFixedWidth(80)
        lbl_timeout.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._combo_ollama_timeout = QComboBox(self._panel_ollama)
        self._combo_ollama_timeout.addItem("180 seconds (3 min)", 180)
        self._combo_ollama_timeout.addItem("360 seconds (6 min - Default)", 360)
        self._combo_ollama_timeout.addItem("600 seconds (10 min)", 600)
        self._combo_ollama_timeout.addItem("900 seconds (15 min)", 900)
        self._combo_ollama_timeout.addItem("1200 seconds (20 min)", 1200)
        row_timeout.addWidget(lbl_timeout)
        row_timeout.addWidget(self._combo_ollama_timeout, stretch=1)
        o_lay.addLayout(row_timeout)

        self._lbl_model_hint = QLabel("", self._panel_ollama)
        self._lbl_model_hint.setStyleSheet("font-size: 10.5px; color: #fbbf24;")
        self._lbl_model_hint.setWordWrap(True)
        o_lay.addWidget(self._lbl_model_hint)

        self._lbl_ollama_status = QLabel("", self._panel_ollama)
        self._lbl_ollama_status.setStyleSheet("font-size: 11px; font-weight: bold;")
        o_lay.addWidget(self._lbl_ollama_status)

        self._card_lay.addWidget(self._panel_ollama)

        # ── Gemini Panel ──
        self._panel_gemini = QWidget(self._card)
        g_lay = QVBoxLayout(self._panel_gemini)
        g_lay.setContentsMargins(0, 0, 0, 0)
        g_lay.setSpacing(8)

        lbl_g_desc = QLabel("High-speed landmark recognition & global visual deduction using Google Gemini.", self._panel_gemini)
        lbl_g_desc.setStyleSheet(f"font-size: 11px; color: {Colors.CYAN_LIGHT};")
        g_lay.addWidget(lbl_g_desc)

        row_gkey = QHBoxLayout()
        lbl_gkey = QLabel("API Key:", self._panel_gemini)
        lbl_gkey.setFixedWidth(80)
        lbl_gkey.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._txt_gemini_key = QLineEdit(self._panel_gemini)
        self._txt_gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._txt_gemini_key.setPlaceholderText("AIzaSy...")
        self._btn_gemini_show = QPushButton("👁", self._panel_gemini)
        self._btn_gemini_show.setFixedWidth(30)
        self._btn_gemini_show.clicked.connect(lambda: self._toggle_echo(self._txt_gemini_key))
        self._btn_test_gemini = QPushButton("🔄 Refresh Models", self._panel_gemini)
        self._btn_test_gemini.clicked.connect(self._refresh_gemini_models)
        row_gkey.addWidget(lbl_gkey)
        row_gkey.addWidget(self._txt_gemini_key, stretch=1)
        row_gkey.addWidget(self._btn_gemini_show)
        row_gkey.addWidget(self._btn_test_gemini)
        g_lay.addLayout(row_gkey)

        row_gmodel = QHBoxLayout()
        lbl_gmodel = QLabel("Model:", self._panel_gemini)
        lbl_gmodel.setFixedWidth(80)
        lbl_gmodel.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._combo_gemini_model = QComboBox(self._panel_gemini)
        self._combo_gemini_model.setEditable(True)
        self._combo_gemini_model.addItems(["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.5-flash", "gemini-1.5-flash-latest"])
        row_gmodel.addWidget(lbl_gmodel)
        row_gmodel.addWidget(self._combo_gemini_model, stretch=1)
        g_lay.addLayout(row_gmodel)

        self._lbl_gemini_status = QLabel("", self._panel_gemini)
        self._lbl_gemini_status.setStyleSheet("font-size: 11px; font-weight: bold;")
        g_lay.addWidget(self._lbl_gemini_status)

        btn_get_gkey = QPushButton("🔗 Get Free Google AI Studio API Key", self._panel_gemini)
        btn_get_gkey.setStyleSheet("color: #38bdf8; text-decoration: underline; background: transparent; border: none; text-align: left; font-size: 11px;")
        btn_get_gkey.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_get_gkey.clicked.connect(lambda: webbrowser.open("https://aistudio.google.com/app/apikey"))
        g_lay.addWidget(btn_get_gkey)

        self._card_lay.addWidget(self._panel_gemini)

        # ── OpenAI Panel ──
        self._panel_openai = QWidget(self._card)
        oa_lay = QVBoxLayout(self._panel_openai)
        oa_lay.setContentsMargins(0, 0, 0, 0)
        oa_lay.setSpacing(8)

        lbl_oa_desc = QLabel("Multimodal GPT-4o vision analysis for fine-grained landmark and text reasoning.", self._panel_openai)
        lbl_oa_desc.setStyleSheet(f"font-size: 11px; color: {Colors.AMBER_LIGHT};")
        oa_lay.addWidget(lbl_oa_desc)

        row_oakey = QHBoxLayout()
        lbl_oakey = QLabel("API Key:", self._panel_openai)
        lbl_oakey.setFixedWidth(80)
        lbl_oakey.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._txt_openai_key = QLineEdit(self._panel_openai)
        self._txt_openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._txt_openai_key.setPlaceholderText("sk-proj-...")
        self._btn_openai_show = QPushButton("👁", self._panel_openai)
        self._btn_openai_show.setFixedWidth(30)
        self._btn_openai_show.clicked.connect(lambda: self._toggle_echo(self._txt_openai_key))
        row_oakey.addWidget(lbl_oakey)
        row_oakey.addWidget(self._txt_openai_key, stretch=1)
        row_oakey.addWidget(self._btn_openai_show)
        oa_lay.addLayout(row_oakey)

        row_oamodel = QHBoxLayout()
        lbl_oamodel = QLabel("Model:", self._panel_openai)
        lbl_oamodel.setFixedWidth(80)
        lbl_oamodel.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._combo_openai_model = QComboBox(self._panel_openai)
        self._combo_openai_model.addItems(["gpt-4o-mini", "gpt-4o"])
        row_oamodel.addWidget(lbl_oamodel)
        row_oamodel.addWidget(self._combo_openai_model, stretch=1)
        oa_lay.addLayout(row_oamodel)

        btn_get_oakey = QPushButton("🔗 OpenAI API Platform Keys", self._panel_openai)
        btn_get_oakey.setStyleSheet("color: #38bdf8; text-decoration: underline; background: transparent; border: none; text-align: left; font-size: 11px;")
        btn_get_oakey.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_get_oakey.clicked.connect(lambda: webbrowser.open("https://platform.openai.com/api-keys"))
        oa_lay.addWidget(btn_get_oakey)

        self._card_lay.addWidget(self._panel_openai)

        # ── DeepSeek Panel ──
        self._panel_deepseek = QWidget(self._card)
        ds_lay = QVBoxLayout(self._panel_deepseek)
        ds_lay.setContentsMargins(0, 0, 0, 0)
        ds_lay.setSpacing(8)

        lbl_ds_desc = QLabel("Forensic reasoning and visual deduction with DeepSeek API (V3/R1).", self._panel_deepseek)
        lbl_ds_desc.setStyleSheet(f"font-size: 11px; color: #60a5fa;")
        ds_lay.addWidget(lbl_ds_desc)

        row_dskey = QHBoxLayout()
        lbl_dskey = QLabel("API Key:", self._panel_deepseek)
        lbl_dskey.setFixedWidth(80)
        lbl_dskey.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._txt_deepseek_key = QLineEdit(self._panel_deepseek)
        self._txt_deepseek_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._txt_deepseek_key.setPlaceholderText("sk-...")
        self._btn_deepseek_show = QPushButton("👁", self._panel_deepseek)
        self._btn_deepseek_show.setFixedWidth(30)
        self._btn_deepseek_show.clicked.connect(lambda: self._toggle_echo(self._txt_deepseek_key))
        row_dskey.addWidget(lbl_dskey)
        row_dskey.addWidget(self._txt_deepseek_key, stretch=1)
        row_dskey.addWidget(self._btn_deepseek_show)
        ds_lay.addLayout(row_dskey)

        row_dsmodel = QHBoxLayout()
        lbl_dsmodel = QLabel("Model:", self._panel_deepseek)
        lbl_dsmodel.setFixedWidth(80)
        lbl_dsmodel.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        self._combo_deepseek_model = QComboBox(self._panel_deepseek)
        self._combo_deepseek_model.setEditable(True)
        self._combo_deepseek_model.addItems(["deepseek-chat", "deepseek-reasoner", "deepseek-vl"])
        row_dsmodel.addWidget(lbl_dsmodel)
        row_dsmodel.addWidget(self._combo_deepseek_model, stretch=1)
        ds_lay.addLayout(row_dsmodel)

        btn_get_dskey = QPushButton("🔗 DeepSeek Platform API Keys", self._panel_deepseek)
        btn_get_dskey.setStyleSheet("color: #38bdf8; text-decoration: underline; background: transparent; border: none; text-align: left; font-size: 11px;")
        btn_get_dskey.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_get_dskey.clicked.connect(lambda: webbrowser.open("https://platform.deepseek.com/api_keys"))
        ds_lay.addWidget(btn_get_dskey)

        self._card_lay.addWidget(self._panel_deepseek)
        layout.addWidget(self._card)

        # Dialog Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton("Cancel", self)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_save = QPushButton("💾 Save Settings", self)
        btn_save.setObjectName("btn_primary")
        btn_save.clicked.connect(self._save_settings)
        btn_row.addWidget(btn_save)

        layout.addLayout(btn_row)

    def _toggle_echo(self, line_edit: QLineEdit):
        if line_edit.echoMode() == QLineEdit.EchoMode.Password:
            line_edit.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            line_edit.setEchoMode(QLineEdit.EchoMode.Password)

    def _on_provider_changed(self, idx: int):
        self._panel_ollama.setVisible(idx == 0)
        self._panel_gemini.setVisible(idx == 1)
        self._panel_openai.setVisible(idx == 2)
        self._panel_deepseek.setVisible(idx == 3)

    def _load_settings(self):
        prov = self._settings.value(SETTINGS_AI_PROVIDER, "ollama", type=str)
        if prov == "gemini":
            self._rb_gemini.setChecked(True)
            self._on_provider_changed(1)
        elif prov == "openai":
            self._rb_openai.setChecked(True)
            self._on_provider_changed(2)
        elif prov == "deepseek":
            self._rb_deepseek.setChecked(True)
            self._on_provider_changed(3)
        else:
            self._rb_ollama.setChecked(True)
            self._on_provider_changed(0)

        # Ollama
        self._txt_ollama_url.setText(self._settings.value(SETTINGS_OLLAMA_URL, "http://localhost:11434", type=str))
        o_model = self._settings.value(SETTINGS_OLLAMA_MODEL, "llama3.2-vision", type=str)
        if self._combo_ollama_model.findText(o_model) == -1:
            self._combo_ollama_model.addItem(o_model)
        self._combo_ollama_model.setCurrentText(o_model)

        o_timeout = self._settings.value(SETTINGS_OLLAMA_TIMEOUT, 360, type=int)
        idx_timeout = self._combo_ollama_timeout.findData(o_timeout)
        if idx_timeout != -1:
            self._combo_ollama_timeout.setCurrentIndex(idx_timeout)
        else:
            self._combo_ollama_timeout.setCurrentIndex(1)  # 360s default

        # Gemini
        self._txt_gemini_key.setText(self._settings.value(SETTINGS_GEMINI_KEY, "", type=str))
        g_model = self._settings.value(SETTINGS_GEMINI_MODEL, "gemini-2.0-flash", type=str)
        if self._combo_gemini_model.findText(g_model) == -1:
            self._combo_gemini_model.addItem(g_model)
        self._combo_gemini_model.setCurrentText(g_model)

        # OpenAI
        self._txt_openai_key.setText(self._settings.value(SETTINGS_OPENAI_KEY, "", type=str))
        oa_model = self._settings.value(SETTINGS_OPENAI_MODEL, "gpt-4o-mini", type=str)
        self._combo_openai_model.setCurrentText(oa_model)

        # DeepSeek
        self._txt_deepseek_key.setText(self._settings.value(SETTINGS_DEEPSEEK_KEY, "", type=str))
        ds_model = self._settings.value(SETTINGS_DEEPSEEK_MODEL, "deepseek-chat", type=str)
        if self._combo_deepseek_model.findText(ds_model) == -1:
            self._combo_deepseek_model.addItem(ds_model)
        self._combo_deepseek_model.setCurrentText(ds_model)

    def _save_settings(self):
        if self._rb_gemini.isChecked():
            prov = "gemini"
        elif self._rb_openai.isChecked():
            prov = "openai"
        elif self._rb_deepseek.isChecked():
            prov = "deepseek"
        else:
            prov = "ollama"

        self._settings.setValue(SETTINGS_AI_PROVIDER, prov)
        self._settings.setValue(SETTINGS_OLLAMA_URL,     self._txt_ollama_url.text().strip() or "http://localhost:11434")
        self._settings.setValue(SETTINGS_OLLAMA_MODEL,   self._combo_ollama_model.currentText().strip() or "llama3.2-vision")
        self._settings.setValue(SETTINGS_OLLAMA_TIMEOUT, int(self._combo_ollama_timeout.currentData() or 360))
        self._settings.setValue(SETTINGS_GEMINI_KEY,     self._txt_gemini_key.text().strip())
        self._settings.setValue(SETTINGS_GEMINI_MODEL,   self._combo_gemini_model.currentText().strip())
        self._settings.setValue(SETTINGS_OPENAI_KEY,     self._txt_openai_key.text().strip())
        self._settings.setValue(SETTINGS_OPENAI_MODEL,   self._combo_openai_model.currentText().strip())
        self._settings.setValue(SETTINGS_DEEPSEEK_KEY,   self._txt_deepseek_key.text().strip())
        self._settings.setValue(SETTINGS_DEEPSEEK_MODEL, self._combo_deepseek_model.currentText().strip())
        self._settings.sync()

        self.accept()

    def _check_vision_model_compatibility(self, model_name: str):
        name = (model_name or "").lower().strip()
        vision_keywords = ["vision", "llava", "minicpm", "vl", "bakllava", "moondream", "gemma3", "qwen3.5", "qwen3.6", "qwen2.5-vl", "qwen2-vl", "qwen-vl"]
        is_vision = any(k in name for k in vision_keywords)
        
        if not name:
            self._lbl_model_hint.setText("")
        elif is_vision:
            self._lbl_model_hint.setText("✓ Multimodal Vision model detected.")
            self._lbl_model_hint.setStyleSheet("font-size: 10.5px; color: #34d399;")
        else:
            self._lbl_model_hint.setText(
                f"ℹ️ Model: '{model_name}'. Ensure this model variant has vision/multimodal support."
            )
            self._lbl_model_hint.setStyleSheet("font-size: 10.5px; color: #38bdf8;")

    def _refresh_ollama_models(self):
        url = self._txt_ollama_url.text().strip() or "http://localhost:11434"
        try:
            self._lbl_ollama_status.setText("⏳ Connecting to Ollama...")
            self._lbl_ollama_status.setStyleSheet("color: #38bdf8;")
            models = AIService.fetch_ollama_models(url)
            if models:
                current = self._combo_ollama_model.currentText()
                self._combo_ollama_model.clear()
                self._combo_ollama_model.addItems(models)
                if current in models:
                    self._combo_ollama_model.setCurrentText(current)
                self._lbl_ollama_status.setText(f"✓ Connected! Found {len(models)} model(s) installed.")
                self._lbl_ollama_status.setStyleSheet(f"color: {Colors.EMERALD_LIGHT};")
                self._check_vision_model_compatibility(self._combo_ollama_model.currentText())
            else:
                self._lbl_ollama_status.setText("✓ Connected, but no models found. Run `ollama pull llama3.2-vision`")
                self._lbl_ollama_status.setStyleSheet(f"color: {Colors.AMBER_LIGHT};")
        except Exception as exc:
            self._lbl_ollama_status.setText(f"✕ Could not connect to {url}: {exc}")
            self._lbl_ollama_status.setStyleSheet(f"color: {Colors.ROSE_LIGHT};")

    def _refresh_gemini_models(self):
        key = self._txt_gemini_key.text().strip()
        if not key:
            self._lbl_gemini_status.setText("✕ Please enter a Google Gemini API Key first.")
            self._lbl_gemini_status.setStyleSheet(f"color: {Colors.AMBER_LIGHT};")
            return
        try:
            self._lbl_gemini_status.setText("⏳ Validating API key & listing models...")
            self._lbl_gemini_status.setStyleSheet("color: #38bdf8;")
            models = AIService.fetch_gemini_models(key)
            if models:
                current = self._combo_gemini_model.currentText()
                self._combo_gemini_model.clear()
                self._combo_gemini_model.addItems(models)
                if current in models:
                    self._combo_gemini_model.setCurrentText(current)
                elif "gemini-2.0-flash" in models:
                    self._combo_gemini_model.setCurrentText("gemini-2.0-flash")
                elif "gemini-1.5-flash" in models:
                    self._combo_gemini_model.setCurrentText("gemini-1.5-flash")
                self._lbl_gemini_status.setText(f"✓ Valid key! Found {len(models)} active model(s).")
                self._lbl_gemini_status.setStyleSheet(f"color: {Colors.EMERALD_LIGHT};")
            else:
                self._lbl_gemini_status.setText("✕ No supported vision models found for this key.")
                self._lbl_gemini_status.setStyleSheet(f"color: {Colors.ROSE_LIGHT};")
        except Exception as exc:
            self._lbl_gemini_status.setText(f"✕ Validation failed: {exc}")
            self._lbl_gemini_status.setStyleSheet(f"color: {Colors.ROSE_LIGHT};")
