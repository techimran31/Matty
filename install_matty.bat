@echo off
REM ===========================================================================
REM install_matty.bat - put Matty on the Desktop and in Windows Startup
REM
REM STEP 1  work out the absolute folder this package lives in
REM STEP 2  create a Desktop shortcut that runs start_matty.bat
REM STEP 3  create the same shortcut in the Startup folder, so Matty opens
REM         automatically when you log in (delete that .lnk to stop it)
REM ===========================================================================
setlocal
set "APP_DIR=%~dp0"
set "TARGET=%APP_DIR%start_matty.bat"

REM STEP 2 - Desktop shortcut
echo Creating Desktop shortcut...
powershell -NoProfile -Command "$desktop=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop 'Matty.lnk')); $s.TargetPath='%TARGET%'; $s.WorkingDirectory='%APP_DIR%'; $s.IconLocation='%SystemRoot%\System32\shell32.dll,14'; $s.Save()"

REM STEP 3 - Startup shortcut (runs at every login)
echo Creating Startup shortcut...
powershell -NoProfile -Command "$startup=[Environment]::GetFolderPath('Startup'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $startup 'Matty.lnk')); $s.TargetPath='%TARGET%'; $s.WorkingDirectory='%APP_DIR%'; $s.IconLocation='%SystemRoot%\System32\shell32.dll,14'; $s.Save()"

echo.
echo [OK] Matty is installed.
echo   Desktop shortcut: Matty
echo   Startup shortcut: Matty (runs automatically at login)
echo.
pause
