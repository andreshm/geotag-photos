"""save_progress_dialog.py — Cyber-Dark modal progress dialog showing live file-by-file saving status with graceful stop support."""

from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QFrame, QWidget, QPushButton
)
from resources.theme import Colors, STYLE_MODERN_CYBER


class SaveProgressDialog(QDialog):
    """Modal progress dialog preventing unsafe interaction while allowing graceful cancellation after the current file."""

    cancel_requested = Signal()

    def __init__(self, total_items: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Applying Changes & Backing Up")
        self.setFixedSize(560, 260)
        self.setStyleSheet(STYLE_MODERN_CYBER)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        # Disable close button during write
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)

        self._total = max(1, total_items)
        self._current = 0
        self._stopping = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)

        # Header Title & Icon
        hdr = QHBoxLayout()
        lbl_icon = QLabel("💾", self)
        lbl_icon.setStyleSheet("font-size: 24px;")
        hdr.addWidget(lbl_icon)

        hdr_text = QVBoxLayout()
        hdr_text.setSpacing(2)
        self._lbl_title = QLabel("Saving & Backing Up Media", self)
        self._lbl_title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {Colors.CYAN_LIGHT};")
        self._lbl_subtitle = QLabel(f"Preparing to process {self._total} item(s)...", self)
        self._lbl_subtitle.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_MUTED};")
        hdr_text.addWidget(self._lbl_title)
        hdr_text.addWidget(self._lbl_subtitle)
        hdr.addLayout(hdr_text)
        hdr.addStretch()
        layout.addLayout(hdr)

        # Progress Bar
        self._progress = QProgressBar(self)
        self._progress.setRange(0, self._total)
        self._progress.setValue(0)
        self._progress.setFixedHeight(18)
        self._progress.setTextVisible(True)
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                background: {Colors.BG_INPUT};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 6px;
                text-align: center;
                color: {Colors.TEXT_PRIMARY};
                font-size: 11px;
                font-weight: bold;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {Colors.CYAN_BG}, stop:1 {Colors.CYAN});
                border-radius: 5px;
            }}
        """)
        layout.addWidget(self._progress)

        # Current File Card Container
        info_frame = QFrame(self)
        info_frame.setStyleSheet(
            f"background: {Colors.BG_PANEL}; border: 1px solid {Colors.BORDER_DEFAULT}; border-radius: 8px;"
        )
        info_lay = QVBoxLayout(info_frame)
        info_lay.setContentsMargins(12, 10, 12, 10)
        info_lay.setSpacing(4)

        # Action / Stage
        self._lbl_stage = QLabel("🛡️ Backing up pristine original files...", info_frame)
        self._lbl_stage.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {Colors.AMBER_LIGHT};")
        info_lay.addWidget(self._lbl_stage)

        # Active File Name
        self._lbl_file = QLabel("Initializing...", info_frame)
        self._lbl_file.setStyleSheet(f"font-family: Consolas, monospace; font-size: 11px; color: {Colors.CYAN_LIGHT};")
        info_lay.addWidget(self._lbl_file)

        layout.addWidget(info_frame)

        # Footer Action Row (Hint + Stop Process Button)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)

        self._lbl_hint = QLabel("💡 Changes are written safely item-by-item to preserve integrity.", self)
        self._lbl_hint.setStyleSheet(f"font-size: 10px; color: {Colors.TEXT_MUTED}; font-style: italic;")
        footer.addWidget(self._lbl_hint, stretch=1)

        self._btn_stop = QPushButton("🛑 Stop Process", self)
        self._btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_stop.setToolTip("Finish current file write safely and stop remaining items without corrupting data")
        self._btn_stop.setStyleSheet(f"""
            QPushButton {{
                background: #230d12;
                border: 1px solid {Colors.ROSE};
                border-radius: 6px;
                color: {Colors.ROSE_LIGHT};
                font-size: 11px;
                font-weight: bold;
                padding: 4px 14px;
                min-height: 24px;
            }}
            QPushButton:hover {{
                background: #3b141d;
                border-color: #fb7185;
                color: #ffffff;
            }}
            QPushButton:disabled {{
                background: #18181b;
                border-color: {Colors.BORDER_DEFAULT};
                color: {Colors.TEXT_MUTED};
            }}
        """)
        self._btn_stop.clicked.connect(self._on_stop_clicked)
        footer.addWidget(self._btn_stop)

        layout.addLayout(footer)

    def _on_stop_clicked(self):
        if self._stopping:
            return
        self._stopping = True
        self._btn_stop.setEnabled(False)
        self._btn_stop.setText("⏳ Stopping safely...")
        self._lbl_stage.setText("⚠️ Stopping after current file finishes writing to preserve integrity...")
        self._lbl_subtitle.setText("Finishing current single file write to preserve file integrity...")
        self.cancel_requested.emit()

    def update_progress(self, current: int, total: int, filename: str = "", stage: str = ""):
        self._current = current
        self._total = total
        self._progress.setRange(0, total)
        self._progress.setValue(current)

        pct = int((current / total) * 100) if total > 0 else 0
        if not self._stopping:
            self._lbl_subtitle.setText(f"Processing item {current} of {total} ({pct}%)")

        if stage and not self._stopping:
            self._lbl_stage.setText(stage)
        if filename:
            self._lbl_file.setText(f"📄 {filename}")

    def reject(self):
        """Prevent user from closing modal while writing is in progress."""
        pass
