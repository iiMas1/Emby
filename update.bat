@echo off
rem Double-click updater for Windows - downloads the latest version into
rem this folder (your .env settings are kept), then re-runs the installer.
cd /d "%~dp0"
(
    echo === Emby / Plex Discord Presence - updater ===
    echo Downloading the latest version...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $zip=Join-Path $env:TEMP 'emby-presence.zip'; $dir=Join-Path $env:TEMP 'emby-presence-update'; Invoke-WebRequest -UseBasicParsing 'https://codeload.github.com/iiMas1/Emby/zip/refs/heads/master' -OutFile $zip; if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }; Expand-Archive -Force $zip $dir; Copy-Item -Force -Recurse (Join-Path $dir 'Emby-master\*') '.'" && (
        echo Updated to the latest version.
        call install.bat
    ) || (
        echo Update failed - check your internet connection and try again.
        pause
    )
    exit /b
)
