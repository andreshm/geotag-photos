"""main.py — entry point for GeoTag Studio PRO with debug logging, crash prevention, and GPU stability flags."""

import os
import sys
import logging
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ── Remote Desktop (RDP) & GPU Stability Setup ──────────────────────────────
is_rdp = (
    os.environ.get("SESSIONNAME", "").lower().startswith("rdp-")
    or bool(os.environ.get("CLIENTNAME"))
    or "--disable-gpu" in sys.argv
    or "--software-render" in sys.argv
)

if is_rdp:
    # RDP virtual display adapters lack hardware D3D/OpenGL swapchains.
    # Force software rasterization so QtWebEngine Chromium renders cleanly without a blank screen.
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        "--disable-gpu --disable-gpu-compositing --disable-gpu-rasterization --no-sandbox"
    )
    os.environ["QT_QUICK_BACKEND"] = "software"
else:
    # Standard desktop: allow hardware acceleration with DirectComposition crash guards
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        "--disable-direct-composition-video-overlays --disable-direct-composition-layers "
        "--disable-features=DirectCompositionVideoOverlays,DirectCompositionLayers "
        "--no-sandbox"
    )

# ── Logging Setup (Console + Rotating File Log) ──────────────────────────────
APP_DIR = Path(__file__).resolve().parent
LOG_FILE = APP_DIR / "geotag_debug.log"

formatter = logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(name)s [%(filename)s:%(lineno)d] — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# File handler (5 MB max, up to 3 backups)
file_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.critical("Uncaught Exception Encountered:", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = handle_exception

logging.info("Starting GeoTag Studio PRO. Log file initialized at: %s", LOG_FILE)

# ── Qt WebEngine Initialization ──────────────────────────────────────────────
from PySide6.QtCore import Qt, QCoreApplication
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

from src.app import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("GeoTag Studio PRO")
    app.setOrganizationName("GeoTag")
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
