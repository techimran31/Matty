@echo off
REM ===========================================================================
REM start_matty_console.bat - Matty without a window (terminal only)
REM
REM Useful for debugging: every voice step prints to this console, and when the
REM microphone cannot be opened the script falls back to typed input.
REM ===========================================================================

cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run install.bat first.
    pause
    exit /b 1
)

REM matty_voice.py runs the six steps in order:
REM STEP 1 key -> STEP 2 microphone -> STEP 3 listen -> STEP 4 wake word
REM -> STEP 5 think -> STEP 6 speak
".venv\Scripts\python.exe" matty_voice.py
pause
