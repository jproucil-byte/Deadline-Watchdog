@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 watchdog.py
  goto done
)
where python >nul 2>nul
if %errorlevel%==0 (
  python watchdog.py
  goto done
)
echo Python was not found. Install it from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during installation.
:done
pause
