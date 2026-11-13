@echo off
REM ===========================================================================
REM set_key.bat - save the free Groq API key into .env
REM
REM STEP 1  work out the folder this script lives in
REM STEP 2  ask for the key and validate it (gsk_ prefix, no spaces)
REM STEP 3  write GROQ_API_KEY=... into .env (replacing an old value if present)
REM ===========================================================================
setlocal enabledelayedexpansion

REM STEP 1 - the .env file lives next to this script
set "ENV_FILE=%~dp0.env"

:ask
REM STEP 2 - collect and validate the key
set "GROQ_KEY="
set /p "GROQ_KEY=Paste your Groq API key (gsk_...) and press Enter: "
if not defined GROQ_KEY goto empty
if not "%GROQ_KEY:~0,4%"=="gsk_" goto badprefix
if not "%GROQ_KEY%"=="%GROQ_KEY: =%" goto badspace
if not "%GROQ_KEY%"=="%GROQ_KEY:	=%" goto badspace

REM STEP 3 - rewrite .env, keeping every other line, replacing GROQ_API_KEY
if not exist "%ENV_FILE%" (
    > "%ENV_FILE%" echo GROQ_API_KEY=%GROQ_KEY%
) else (
    set "FOUND="
    > "%ENV_FILE%.tmp" (
        for /f "usebackq delims=" %%L in ("%ENV_FILE%") do (
            set "LINE=%%L"
            if "!LINE:GROQ_API_KEY=!"=="!LINE!" (
                echo %%L
            ) else (
                if not defined FOUND (
                    echo GROQ_API_KEY=%GROQ_KEY%
                    set "FOUND=1"
                )
            )
        )
        if not defined FOUND echo GROQ_API_KEY=%GROQ_KEY%
    )
    move /y "%ENV_FILE%.tmp" "%ENV_FILE%" >nul
)

echo [OK] Key saved to %ENV_FILE%
echo Now run: start_matty.bat
pause
exit /b 0

:empty
echo No key entered. Nothing changed.
pause
exit /b 1

:badprefix
echo [X] That does not start with "gsk_". Please copy only the key.
pause
goto ask

:badspace
echo [X] The key contains spaces. Please copy only the key, no command text.
pause
goto ask
