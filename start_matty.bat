@echo off
REM ===========================================================================
REM start_matty.bat - launch the Matty holographic HUD
REM
REM STEP 1  move into the folder this file lives in (relative paths work)
REM STEP 2  refuse to start when the virtual environment is missing
REM STEP 3  run the HUD (matty_hud.py = pywebview window + voice loop)
REM STEP 4  if the HUD cannot start, fall back to the tkinter window
REM ===========================================================================

REM STEP 1 - always run from the package folder
cd /d "%~dp0"

REM STEP 2 - the venv holds all dependencies
if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run install.bat first.
    pause
    exit /b 1
)

REM STEP 3 - the holographic HUD
".venv\Scripts\python.exe" matty_hud.py

REM STEP 4 - fallback when the HUD window could not be created
if errorlevel 1 (
    echo.
    echo Holographic HUD could not start. Launching the standard interface...
    ".venv\Scripts\python.exe" matty_ui.py
)
pause
