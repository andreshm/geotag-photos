@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo  GeoTag Studio PRO — First-Time Setup
echo ============================================================
echo.

:: Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python was not detected on this system.
        echo Please install Python 3.10+ from https://python.org
        echo (IMPORTANT: Check the box "Add Python to PATH" during installation)
        echo.
        pause & exit /b 1
    ) else (
        set PY_CMD=py
    )
) else (
    set PY_CMD=python
)

echo [1/3] Preparing clean virtual environment for this computer...

:: If .venv was copied from another machine, delete the stale directory first
if exist .venv (
    echo       Removing old .venv copied from another computer...
    rmdir /s /q .venv >nul 2>&1
)

%PY_CMD% -m venv --clear .venv
if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    echo Trying fallback without ensurepip...
    %PY_CMD% -m venv --without-pip --clear .venv
    call .venv\Scripts\activate.bat
    %PY_CMD% -m ensurepip --upgrade
)

if not exist .venv\Scripts\activate.bat (
    echo [ERROR] Virtual environment creation failed.
    pause & exit /b 1
)

echo [2/3] Activating virtual environment & installing dependencies...
call .venv\Scripts\activate.bat

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Package installation encountered an error.
    pause & exit /b 1
)

echo [3/3] Setup complete!
echo.
echo ============================================================
echo  Setup Succeeded!
echo  To launch GeoTag Studio PRO at any time, run:
echo    run.bat  (or python main.py)
echo ============================================================
echo.

:: Create a convenient 1-click launcher run.bat if missing
if not exist run.bat (
    (
        echo @echo off
        echo cd /d "%%~dp0"
        echo call .venv\Scripts\activate.bat
        echo start pythonw main.py
    ) > run.bat
)

pause
