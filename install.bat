@echo off
rem Double-click installer for Windows - sets everything up and can enable
rem start-at-logon. Safe to run again any time.
cd /d "%~dp0"
echo === Emby / Plex Discord Presence - installer ===

where py >nul 2>nul
if not errorlevel 1 (
    set "PY=py"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python 3 is required but was not found.
        echo Install it from https://www.python.org/downloads/ and tick
        echo "Add python.exe to PATH" in the installer, then run this again.
        pause
        exit /b 1
    )
    set "PY=python"
)

if not exist .venv (
    echo Creating Python environment...
    %PY% -m venv .venv
)
echo Installing dependencies...
.venv\Scripts\pip install -q -r requirements.txt

if exist .env (
    set /p AGAIN="Already configured - run the sign-in setup again? [y/N] "
) else (
    set "AGAIN=y"
)
if /i "%AGAIN%"=="y" .venv\Scripts\python setup.py

set /p AUTOSTART="Start automatically when you log on? [Y/n] "
if /i "%AUTOSTART%"=="n" (
    echo Run it any time with:  .venv\Scripts\python emby_discord_presence.py
) else (
    (
        echo @echo off
        echo cd /d "%~dp0"
        echo start "" "%~dp0.venv\Scripts\pythonw.exe" emby_discord_presence.py
    ) > "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\emby-discord-presence.bat"
    start "" "%~dp0.venv\Scripts\pythonw.exe" emby_discord_presence.py
    echo Installed and running - it starts automatically at logon.
)
pause
