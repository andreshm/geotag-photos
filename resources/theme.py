"""theme.py — Modern Cyber-Dark Glassmorphic Design System.
Inspired by the IIS Sentinel / Log Viewer UI aesthetic.
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# Color Tokens
# ─────────────────────────────────────────────────────────────────────────────
class Colors:
    # Canvas & Backgrounds
    BG_CANVAS        = "#070b14"   # Main application background
    BG_PANEL         = "#0d1527"   # Secondary panel background
    BG_CARD          = "#111c35"   # Card widget background
    BG_CARD_HOVER    = "#18274a"   # Card hover state
    BG_SURFACE       = "#0f172a"   # Dropdowns, menus, overlays
    BG_INPUT         = "#0b1222"   # Input fields & controls

    # Borders & Dividers
    BORDER_SUBTLE    = "rgba(255, 255, 255, 0.07)"
    BORDER_DEFAULT   = "#1e293b"
    BORDER_FOCUS     = "#06b6d4"   # Cyan glow on focus
    BORDER_CARD      = "#1a2744"

    # Brand & Neon Accents
    CYAN             = "#06b6d4"   # Primary brand / glow
    CYAN_LIGHT       = "#67e8f9"
    CYAN_BG          = "#083344"
    BLUE             = "#3b82f6"   # Secondary accent
    BLUE_DARK        = "#1d4ed8"
    BLUE_BG          = "#172554"   # Deep indigo/blue badge background
    EMERALD          = "#10b981"   # Geotagged / Success
    EMERALD_LIGHT    = "#6ee7b7"
    EMERALD_BG       = "#064e3b"
    AMBER            = "#f59e0b"   # Pending changes / Warning
    AMBER_LIGHT      = "#fcd34d"
    AMBER_BG         = "#78350f"
    ROSE             = "#f43f5e"   # Missing GPS / Danger
    ROSE_LIGHT       = "#fda4af"
    ROSE_BG          = "#881337"
    PURPLE           = "#a855f7"   # RAW+JPEG pairing
    PURPLE_LIGHT     = "#d8b4fe"
    PURPLE_BG        = "#581c87"

    # Typography
    TEXT_PRIMARY     = "#f8fafc"   # High-contrast white/slate
    TEXT_SECONDARY   = "#94a3b8"   # Slate 400
    TEXT_MUTED       = "#64748b"   # Slate 500
    TEXT_DISABLED    = "#475569"   # Slate 600

# ─────────────────────────────────────────────────────────────────────────────
# Qt Global Stylesheet (QSS)
# ─────────────────────────────────────────────────────────────────────────────
STYLE_MODERN_CYBER = f"""
/* ── Global Reset ── */
QMainWindow, QDialog, QWidget {{
    background-color: {Colors.BG_CANVAS};
    color: {Colors.TEXT_PRIMARY};
    font-family: 'Segoe UI', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 12px;
}}

/* ── Splitters ── */
QSplitter::handle {{
    background: {Colors.BORDER_DEFAULT};
}}
QSplitter::handle:horizontal {{
    width: 2px;
}}
QSplitter::handle:vertical {{
    height: 2px;
}}
QSplitter::handle:hover {{
    background: {Colors.CYAN};
}}

/* ── ToolBar ── */
QToolBar {{
    background: {Colors.BG_PANEL};
    border: none;
    border-bottom: 1px solid {Colors.BORDER_DEFAULT};
    padding: 6px 12px;
    spacing: 8px;
}}
QToolBar::separator {{
    background: {Colors.BORDER_DEFAULT};
    width: 1px;
    margin: 4px 6px;
}}

/* ── PushButtons ── */
QPushButton {{
    background: {Colors.BG_CARD};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER_DEFAULT};
    border-radius: 6px;
    padding: 5px 12px;
    font-weight: 500;
    font-size: 11px;
    min-height: 24px;
}}
QPushButton:hover {{
    background: {Colors.BG_CARD_HOVER};
    border-color: {Colors.CYAN};
    color: #ffffff;
}}
QPushButton:pressed {{
    background: #0c1830;
}}
QPushButton:disabled {{
    background: #090e1a;
    color: {Colors.TEXT_DISABLED};
    border-color: #121b2d;
}}

/* Primary Glow Button (Cyan/Blue Gradient) */
QPushButton#btn_primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #06b6d4, stop:1 #2563eb);
    color: #040814;
    border: 1px solid #38bdf8;
    border-radius: 6px;
    font-weight: 700;
}}
QPushButton#btn_primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #22d3ee, stop:1 #3b82f6);
    border-color: #7dd3fc;
    color: #000000;
}}
QPushButton#btn_primary:disabled {{
    background: #11253a;
    color: #334155;
    border-color: #0f1e30;
}}

/* Action Buttons */
QPushButton#btn_action_amber {{
    background: #1c1305;
    border: 1px solid {Colors.AMBER};
    color: {Colors.AMBER_LIGHT};
    border-radius: 6px;
    font-weight: 600;
}}
QPushButton#btn_action_amber:hover {{
    background: {Colors.AMBER_BG};
    color: #ffffff;
}}

QPushButton#btn_action_emerald {{
    background: #061c14;
    border: 1px solid {Colors.EMERALD};
    color: {Colors.EMERALD_LIGHT};
    border-radius: 6px;
    font-weight: 600;
}}
QPushButton#btn_action_emerald:hover {{
    background: {Colors.EMERALD_BG};
    color: #ffffff;
}}

QPushButton#btn_action_purple {{
    background: #180928;
    border: 1px solid {Colors.PURPLE};
    color: {Colors.PURPLE_LIGHT};
    border-radius: 6px;
    font-weight: 600;
}}
QPushButton#btn_action_purple:hover {{
    background: {Colors.PURPLE_BG};
    color: #ffffff;
}}

/* Filter Chip Buttons */
QPushButton.filter_chip {{
    background: {Colors.BG_INPUT};
    color: {Colors.TEXT_SECONDARY};
    border: 1px solid {Colors.BORDER_DEFAULT};
    border-radius: 13px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 600;
    min-height: 22px;
}}
QPushButton.filter_chip:hover {{
    border-color: {Colors.CYAN};
    color: {Colors.TEXT_PRIMARY};
}}
QPushButton.filter_chip:checked {{
    background: #082f49;
    border-color: {Colors.CYAN};
    color: {Colors.CYAN_LIGHT};
}}

/* ── Inputs & SpinBoxes ── */
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
    background: {Colors.BG_INPUT};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER_DEFAULT};
    border-radius: 5px;
    padding: 3px 8px;
    min-height: 24px;
    font-size: 11px;
    selection-background-color: #0284c7;
    selection-color: #ffffff;
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {Colors.CYAN};
    background: #0c162c;
}}
QComboBox::drop-down {{
    border: none;
    padding-right: 6px;
}}
QComboBox QAbstractItemView {{
    background: {Colors.BG_SURFACE};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER_DEFAULT};
    selection-background-color: #0c2340;
    selection-color: {Colors.CYAN_LIGHT};
}}

/* ── CheckBoxes ── */
QCheckBox {{
    color: {Colors.TEXT_PRIMARY};
    spacing: 6px;
    font-size: 11px;
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {Colors.BORDER_DEFAULT};
    border-radius: 3px;
    background: {Colors.BG_INPUT};
}}
QCheckBox::indicator:hover {{
    border-color: {Colors.CYAN};
}}
QCheckBox::indicator:checked {{
    background: #0284c7;
    border-color: {Colors.CYAN};
    image: none;
}}

/* ── Progress Bar ── */
QProgressBar {{
    background: {Colors.BG_INPUT};
    border: 1px solid {Colors.BORDER_DEFAULT};
    border-radius: 3px;
    text-align: center;
    color: {Colors.TEXT_PRIMARY};
    font-size: 10px;
    font-weight: bold;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #06b6d4, stop:1 #3b82f6);
    border-radius: 2px;
}}

/* ── GroupBox & Frames ── */
QGroupBox {{
    border: 1px solid {Colors.BORDER_DEFAULT};
    border-radius: 6px;
    margin-top: 10px;
    padding: 8px 8px 6px 8px;
    color: {Colors.TEXT_SECONDARY};
    font-weight: 600;
    font-size: 11px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {Colors.CYAN};
    font-weight: 700;
}}

/* ── ScrollBars ── */
QScrollBar:vertical {{
    background: {Colors.BG_CANVAS};
    width: 7px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #1e293b;
    border-radius: 3px;
    min-height: 25px;
}}
QScrollBar::handle:vertical:hover {{
    background: {Colors.CYAN};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {Colors.BG_CANVAS};
    height: 7px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: #1e293b;
    border-radius: 3px;
    min-width: 25px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {Colors.CYAN};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Table & Tree Widgets ── */
QTableWidget, QTreeView, QTreeWidget {{
    background: {Colors.BG_INPUT};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER_DEFAULT};
    border-radius: 6px;
    gridline-color: rgba(255, 255, 255, 0.05);
    selection-background-color: #0c2340;
    selection-color: {Colors.CYAN_LIGHT};
}}
QHeaderView::section {{
    background: {Colors.BG_CARD};
    color: {Colors.TEXT_SECONDARY};
    border: none;
    border-right: 1px solid {Colors.BORDER_DEFAULT};
    border-bottom: 1px solid {Colors.BORDER_DEFAULT};
    padding: 6px 10px;
    font-weight: 600;
    font-size: 11px;
}}

/* ── Menus ── */
QMenu {{
    background: {Colors.BG_SURFACE};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER_DEFAULT};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 20px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: #082f49;
    color: {Colors.CYAN_LIGHT};
}}
QMenu::separator {{
    height: 1px;
    background: {Colors.BORDER_DEFAULT};
    margin: 4px 6px;
}}

/* ── StatusBar ── */
QStatusBar {{
    background: {Colors.BG_PANEL};
    color: {Colors.TEXT_SECONDARY};
    border-top: 1px solid {Colors.BORDER_DEFAULT};
    font-size: 11px;
    padding: 2px 8px;
}}

/* ── ToolTips ── */
QToolTip {{
    background: {Colors.BG_SURFACE};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.CYAN};
    border-radius: 4px;
    padding: 6px 8px;
    font-size: 11px;
}}
"""
