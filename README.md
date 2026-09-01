# 📍 GeoTag Studio PRO

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/GUI-PySide6%20%2F%20Qt6-green?style=for-the-badge&logo=qt&logoColor=white" alt="PySide6 / Qt6" />
  <img src="https://img.shields.io/badge/Engine-ExifTool-orange?style=for-the-badge" alt="ExifTool" />
  <img src="https://img.shields.io/badge/Maps-Leaflet%20%26%20OpenStreetMap-blueviolet?style=for-the-badge&logo=leaflet&logoColor=white" alt="Leaflet & OSM" />
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey?style=for-the-badge" alt="Cross Platform" />
  <img src="https://img.shields.io/badge/License-MIT-emerald?style=for-the-badge" alt="MIT License" />
</p>

<h3 align="center">
  <b>A modern, high-performance desktop studio for visual geotagging, timeline GPS interpolation, metadata synchronization, and automated photo & video backups.</b>
</h3>

---

## 🌟 Why GeoTag Studio PRO?

Unlike simple EXIF editors, **GeoTag Studio PRO** is built for high-volume travel photographers, drone pilots, and family archivists. It effortlessly handles mixed batches of photos, 4K videos, paired RAW+JPEG files, and network shares with zero data loss.

```
       ┌─────────────────────────────────────────────────────────────┐
       │                   GeoTag Studio PRO                         │
       ├──────────────────────────────┬──────────────────────────────┤
       │       Interactive Map        │     Multi-Select Gallery     │
       │   • Esri Cyber Dark Canvas   │   • Instant Flat / Folders   │
       │   • OpenStreetMap & Topo     │   • Multi-Criteria Filtering │
       │   • Satellite Hybrid Imagery │   • RAW+JPEG Auto-Pairing    │
       │   • Nominatim Global Search  │   • Live GPS Badges          │
       ├──────────────────────────────┴──────────────────────────────┤
       │   ⚡ Timeline GPS Auto-Tagger & Linear Interpolator          │
       │   🛡️ Mirrored Directory Backup Center & 1-Click Restore     │
       │   🔄 Smart PNG-to-JPEG Conversion & Self-Healing EXIF        │
       └─────────────────────────────────────────────────────────────┘
```

---

## ✨ Key Features

### 🗺️ Interactive Multi-Basemap Studio
* **100% Free, Key-Free Basemaps**: Built-in support for **Cyber Dark Canvas (Esri)**, **OpenStreetMap**, **Esri Satellite Hybrid (Imagery + Labels)**, and **Topographic maps**.
* **Global Search**: Search any city, landmark, or address via built-in Nominatim geocoding.
* **Instant Coordinates**: Click anywhere on the map or paste GPS coordinates / Google Maps URLs to drop a live pulsing pin.
* **Smooth Auto-Centering**: Selecting any geotagged photo or video smoothly flies the camera to the exact coordinates on the map.

### ⚡ Timeline Auto-Tagger & Linear Interpolation
* **Smart Timeline Geocoding**: Automatically tags missing media using timestamps from surrounding photos taken along your route.
* **Linear GPS Interpolation**: Accurately calculates intermediate coordinates along your travel path between known GPS anchor points within configurable time gaps.

### 🎬 Full Video & RAW+JPEG Synchronization
* **4K & High-Bitrate Video Tagging**: Writes ISO-standard QuickTime GPS tags (`Keys:GPSCoordinates`, `UserData:GPSCoordinates`) to `.mp4`, `.mov`, `.3gp`, DJI, GoPro, and Sony drone/action-cam videos.
* **RAW+JPEG Pairing**: Automatically links RAW files (`.cr2`, `.cr3`, `.nef`, `.arw`, `.dng`, `.raf`, `.orf`, etc.) with their companion JPEGs, presenting a single clean card while updating metadata on both files.

### 🛡️ Non-Destructive Mirrored Backup Center
* **Pre-Write Safety Engine**: Automatically creates full mirrored backups of original files before modifying any metadata.
* **Smart Collision Protection**: Windows-style duplicate handling (`file (1).jpg`, `file (2).jpg`) preserves full historical versions.
* **Backup Center UI**: Browse, inspect, and 1-click restore individual files or entire folders at any time.

### 🔄 PNG-to-JPEG Conversion & Self-Healing EXIF
* **Smart PNG Conversion**: Automatically converts screenshots, phone graphics, and format-mismatched PNGs to 95% quality JPEGs, preserving orientation and compositing transparency onto white.
* **Self-Healing EXIF Repair**: Automatically catches and repairs corrupt camera pointers (e.g. Samsung Galaxy `OtherImageStart in IFD0` errors) without losing timestamps or color profiles.

### 🎯 Unified Multi-Select Filter Toolbar
* **Compact Glassmorphic Toolbar**: Dropdown filter supporting multi-selection across GPS statuses (`🔴 Missing GPS`, `⏳ Staged`, `✓ Geotagged`) and Media types (`🎬 Videos`, `📦 RAW Pairs`).
* **Fast Navigation**: Jump between untagged photos instantly using `F3` / `Shift+F3` or `Alt+Up` / `Alt+Down`.

### 🖥️ Remote Desktop (RDP) & Network Share Optimized
* **RDP Compatible**: Automatically detects Remote Desktop virtual display drivers and switches to software rasterization, preventing blank screen issues.
* **Safe Batch Writes**: Modal live progress dialog shows file-by-file status, locking out accidental concurrent actions during long network share writes.

---

## 🚀 Quick Start

### Prerequisites
1. **Python 3.10+** ([Download Python](https://python.org)) — *Check "Add Python to PATH" during installation.*
2. **ExifTool** ([Download ExifTool](https://exiftool.org/)) — *Place `exiftool.exe` in the application folder.*

### 1. Installation

Clone the repository:
```bash
git clone https://github.com/andreshm/geotag-photos.git
cd geotag-photos
```

Run the automated 1-click setup:
```bash
# Windows
setup.bat

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Launch the Application

```bash
# Windows (1-Click)
run.bat

# Or via terminal
python main.py
```

---

## 📦 Building a Standalone Portable App

To create a standalone portable `.exe` folder that runs on any Windows PC without needing Python installed:

```bash
.\build_exe.bat
```
*(The compiled, self-contained application will be generated in `dist/GeoTagStudioPRO/`).*

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| `Ctrl + O` | Open Photo & Video Folder(s) |
| `Ctrl + S` | Save & Write All Staged Changes |
| `Ctrl + A` | Select All Visible Media |
| `Escape` | Deselect All Media |
| `F3` / `Alt + Down` | Jump to Next Untagged Media Item |
| `Shift + F3` / `Alt + Up` | Jump to Previous Untagged Media Item |
| `Delete` | Erase GPS Coordinates from Selected Items |
| `Ctrl + +` / `Ctrl + -` | Zoom Grid Thumbnails In / Out |

---

## 🏗️ Project Architecture

```
geotag-photos/
├── main.py                  # Application entry point & GPU/RDP environment initialization
├── setup.bat                # Automated 1-click venv setup & package installer
├── run.bat                  # Instant 1-click launcher
├── build_exe.bat            # PyInstaller portable build script
├── requirements.txt         # Python package dependencies
├── resources/
│   ├── map.html             # Leaflet.js interactive map & custom Cyber-Dark tile engine
│   └── theme.py             # Cyber-Dark Glassmorphic UI design tokens & QSS styles
└── src/
    ├── app.py               # Main window controller, toolbar & save lifecycle
    ├── photo_grid.py        # High-performance card grid with multi-filter dropdown
    ├── map_widget.py        # QWebEngineView map wrapper & QWebChannel bridge
    ├── photo_preview.py     # Slide-out metadata inspector & EXIF card
    ├── photo_manager.py     # ExifTool engine, metadata parsing & self-healing repair
    ├── auto_tagger.py       # Timeline GPS auto-tagger & linear interpolation
    ├── backup_manager.py    # Mirrored directory backup engine & Backup Center dialog
    ├── save_progress_dialog.py # Modal file-by-file saving progress indicator
    ├── session_manager.py   # Crash recovery & staged state persistence
    ├── thumbnail_cache.py   # Two-tier memory + disk thumbnail caching
    └── workers.py           # Background QThread workers (Scanning, Thumbnails, Saving)
```

---

## 📄 License

This project is open source and available under the [MIT License](LICENSE).
