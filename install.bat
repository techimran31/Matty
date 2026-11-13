@echo off
REM ==============================================================================
REM  MATTY AI PERSONAL ASSISTANT - 1-CLICK WINDOWS SETUP SCRIPT
REM
REM  STEP 1  check that Python 3.10+ is installed and on PATH
REM  STEP 2  create the virtual environment (.venv) if it is missing
REM  STEP 3  activate that environment
REM  STEP 4  upgrade pip
REM  STEP 5  install requirements.txt (speech, audio, GUI, market libs)
REM  STEP 6  store the free Groq API key (or skip -> offline mode)
REM  STEP 7  print the next steps and start Matty
REM ==============================================================================

setlocal enabledelayedexpansion

echo.
echo ==================================================================
echo           WELCOME TO MATTY AI ASSISTANT SETUP
echo ==================================================================
echo.

REM STEP 1 - is Python available at all?
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Python is NOT installed or not in PATH
    echo.
    echo Please install Python 3.10+ from: https://python.org
    echo.
    echo IMPORTANT: During installation, CHECK the box:
    echo "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

echo [OK] Python detected successfully!
echo.

REM STEP 2 - create .venv (all dependencies are installed inside it, so the
REM rest of the system stays untouched)
if not exist ".venv" (
    echo [*] Creating virtual environment (.venv)...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [X] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created!
    echo.
) else (
    echo [OK] Virtual environment already exists!
    echo.
)

REM STEP 3 - activate .venv for the rest of this script
echo [*] Activating virtual environment...
call .venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo [X] Failed to activate virtual environment
    pause
    exit /b 1
)
echo [OK] Virtual environment activated!
echo.

REM STEP 4 - pip first, so the packages below resolve correctly
REM NOTE: always call pip as "python -m pip", never as pip.exe. Windows
REM Application Control / Smart App Control can block pip.exe, which produces
REM "An Application Control policy has blocked this file". python.exe is not
REM blocked, so the module form always works.
echo [*] Upgrading pip...
python -m pip install --upgrade pip
if %errorlevel% neq 0 (
    echo [!] Warning: pip upgrade had issues, continuing anyway...
)
echo.

REM STEP 5 - install the dependencies
REM   openai            cloud + whisper speech-to-text
REM   SpeechRecognition microphone capture and Google fallback
REM   openai/requests   network calls
REM   customtkinter     the classic window
REM   pyttsx3/pywin32   speech output
REM   pyaudiowpatch     PyAudio replacement with Python 3.14 wheels
REM   pycaw             volume control
REM   yt-dlp/pywhatkit  YouTube and WhatsApp
echo [*] Installing dependencies from requirements.txt...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [X] Failed to install requirements
    echo.
    echo Try running manually:
    echo   1. Open Command Prompt in this folder
    echo   2. Run: .venv\Scripts\activate.bat
    echo   3. Run: python -m pip install -r requirements.txt
    pause
    exit /b 1
)
echo [OK] Dependencies installed!
echo.

REM Audio packages are listed in requirements.txt (pyttsx3, PyAudioWPatch, pycaw)

REM STEP 6 - Groq API key (optional; without it Matty runs offline)
REM The key is stored in .env as GROQ_API_KEY, next to this script.
set "ENV_FILE=%~dp0.env"
if exist "%ENV_FILE%" (
    findstr /b /c:"GROQ_API_KEY=" "%ENV_FILE%" >nul 2>&1 && (
        echo [OK] Found existing Groq API key in .env!
        goto key_done
    )
)
echo.
echo Get a FREE Groq API key from: https://console.groq.com/keys
set /p GROQ_KEY=Enter Groq API Key (or press Enter to skip and use offline mode): 
if defined GROQ_KEY (
    >> "%ENV_FILE%" echo GROQ_API_KEY=!GROQ_KEY!
    echo [OK] API key saved to .env.
) else (
    echo [!] Skipping API key. Matty will run in local offline mode.
)
:key_done
echo.

REM STEP 7 - summary and first launch
echo.
echo ==================================================================
echo [+] MATTY SETUP COMPLETED SUCCESSFULLY!
echo ==================================================================
echo.
echo NEXT STEPS:
echo.
echo 1. Get your FREE Groq API key:
echo    Visit: https://console.groq.com/keys
echo.
echo 2. To start Matty later, double-click start_matty.bat
echo.
echo 3. The first time, Matty will ask for your Groq API key
echo    (You can skip it and use offline mode)
echo.
pause

REM Start Matty
echo.
echo [*] Starting Matty AI Assistant...
echo.
python matty_voice.py
