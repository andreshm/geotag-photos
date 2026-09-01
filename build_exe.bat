@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo  GeoTag Studio PRO — Build Standalone Portable Package
echo ============================================================
echo.

call .venv\Scripts\activate.bat

python -m pip install --upgrade pyinstaller

echo.
echo Building portable distribution (Device-Guard safe via python module)...
python -m PyInstaller ^
  --name "GeoTagStudioPRO" ^
  --noconfirm ^
  --clean ^
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

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Check the error messages above.
    pause
    exit /b 1
)

if exist exiftool.exe (
    if not exist "dist\GeoTagStudioPRO" mkdir "dist\GeoTagStudioPRO"
    echo Copying exiftool.exe into dist\GeoTagStudioPRO\...
    copy /y exiftool.exe "dist\GeoTagStudioPRO\" >nul
)

echo.
echo ============================================================
echo  Build complete!
echo  Portable output folder: dist\GeoTagStudioPRO\
echo ============================================================
echo.
pause
