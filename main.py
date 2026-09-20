"""main.py — entry point for GeoTag Studio PRO with debug logging, crash prevention, and GPU stability flags."""

import os
import sys
import logging
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ── Remote Desktop (RDP) & GPU Stability Setup ──────────────────────────────
def is_remote_or_software_render() -> bool:
    """Detects if the session is running under Remote Desktop (RDP), a virtual display, or software mode."""
    # 1. Native Windows Win32 API Check (SM_REMOTESESSION = 0x1000, SM_REMOTECONTROL = 0x2001)
    try:
        import ctypes
        if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "user32"):
            if ctypes.windll.user32.GetSystemMetrics(0x1000) != 0:
                return True
            if ctypes.windll.user32.GetSystemMetrics(0x2001) != 0:
                return True
    except Exception:
        pass

    # 2. Environment Variables Check
    sess = os.environ.get("SESSIONNAME", "").lower()
    if sess and sess != "console" and any(k in sess for k in ("rdp", "tcp", "ica", "citrix", "term")):
        return True
    if bool(os.environ.get("CLIENTNAME")):
        return True
    if any(k in os.environ for k in ("SSH_CONNECTION", "SSH_CLIENT", "XRDP_SESSION", "REMOTE_DESKTOP", "VNC_SERVER")):
        return True

    # 3. Explicit Command Line Flags
    if any(arg in sys.argv for arg in ("--disable-gpu", "--software-render", "--rdp", "--no-gpu", "--software")):
        return True

    # 4. User Preference in QSettings
    try:
        from PySide6.QtCore import QSettings
        settings = QSettings("GeoTag", "GeoTagStudioPRO")
        if settings.value("ui/force_software_render", False, type=bool):
            return True
    except Exception:
        pass

    return False


is_rdp = is_remote_or_software_render()

if is_rdp:
    # RDP virtual display adapters lack hardware D3D/OpenGL swapchains.
    # Force software rasterization so QtWebEngine Chromium renders cleanly without a blank screen.
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        "--disable-gpu "
        "--disable-gpu-compositing "
        "--disable-gpu-rasterization "
        "--disable-accelerated-2d-canvas "
        "--disable-accelerated-video-decode "
        "--in-process-gpu "
        "--no-sandbox"
    )
    os.environ["QT_QUICK_BACKEND"] = "software"
    os.environ["QT_OPENGL"] = "software"
    os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
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
if is_rdp:
    logging.info("Applying AA_UseSoftwareOpenGL for remote/software render mode.")
    if hasattr(Qt.ApplicationAttribute, "AA_UseSoftwareOpenGL"):
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)

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
