@echo off
echo ============================================================
echo  GeoTag Photos — Build standalone EXE (PyInstaller)
echo ============================================================
echo.

call .venv\Scripts\activate.bat

pip install pyinstaller

pyinstaller ^
  --name "GeoTag Photos" ^
  --onedir ^
  --windowed ^
  --icon NONE ^
  --add-data "resources;resources" ^
  --hidden-import "PySide6.QtWebEngineWidgets" ^
  --hidden-import "PySide6.QtWebEngineCore" ^
  --hidden-import "PySide6.QtWebChannel" ^
  --hidden-import "rawpy" ^
  --hidden-import "exiftool" ^
  main.py

echo.
echo ============================================================
echo  Build complete!  Output: dist\GeoTag Photos\
echo  Copy exiftool.exe into dist\GeoTag Photos\ before shipping.
echo ============================================================
pause
