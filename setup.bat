@echo off
echo ============================================================
echo  GeoTag Photos — First-time setup
echo ============================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found.  Install Python 3.11+ from https://python.org
    pause & exit /b 1
)

echo [1/3] Creating virtual environment...
python -m venv .venv
if errorlevel 1 ( echo FAILED & pause & exit /b 1 )

echo [2/3] Activating venv and installing packages...
call .venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 ( echo FAILED & pause & exit /b 1 )

echo [3/3] Done!
echo.
echo ============================================================
echo  IMPORTANT: You also need ExifTool
echo  Download from:  https://exiftool.org/  (Windows Executable)
echo  Place exiftool.exe in this folder:
echo    %~dp0
echo ============================================================
echo.
echo To run the app:
echo   .venv\Scripts\activate.bat
echo   python main.py
echo.
pause
