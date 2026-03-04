"""main.py — entry point for GeoTag Photos."""

import sys
import logging
from pathlib import Path

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

# ── Qt WebEngine must be initialised before QApplication on some platforms ────
from PySide6.QtCore import Qt, QCoreApplication
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView    # ensure QtWebEngine is loaded

from src.app import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("GeoTag Photos")
    app.setOrganizationName("GeoTag")
    app.setStyle("Fusion")   # consistent cross-platform base

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
