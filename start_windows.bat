@echo off
cd /d "%~dp0"
echo Starting music-Ai ...
set PY=python
where py >nul 2>nul && set PY=py
%PY% -c "import numpy, yaml, yt_dlp, imageio_ffmpeg" 2>nul
if errorlevel 1 (
  echo Installing / updating required libraries ^(first run or after an update^)...
  %PY% -m pip install -r requirements.txt
)
%PY% -m musicai app
if errorlevel 1 (
  echo.
  echo Could not start. Please install Python 3.10+ from https://www.python.org/downloads/
  echo and check "Add python.exe to PATH" during installation.
  pause
)
