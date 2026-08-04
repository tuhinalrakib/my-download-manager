@echo off
title YouTube Video Downloader - StreamPull
color 0A

echo ========================================================
echo         YouTube Video Downloader - StreamPull
echo ========================================================
echo.

:: Check Python installation
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not added to PATH!
    echo Please install Python from https://www.python.org/ and check "Add Python to PATH".
    pause
    exit /b
)

:: Create virtual environment if it doesn't exist
if not exist "venv" (
    echo [INFO] Creating Python virtual environment...
    python -m venv venv
)

:: Activate virtual environment
call venv\Scripts\activate.bat

echo [INFO] Installing / Updating dependencies (flask, yt-dlp)...
pip install -r requirements.txt --quiet

:: Check FFmpeg
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    if not exist "ffmpeg.exe" (
        echo.
        echo [INFO] Installing FFmpeg for 1080p, 4K & MP3 merging support...
        python download_ffmpeg.py
    )
)

echo.
echo ========================================================
echo [SUCCESS] Server starting at http://localhost:5000
echo Opening browser automatically...
echo ========================================================
echo.

:: Open browser after 2 seconds
timeout /t 2 /nobreak >nul
start http://localhost:5000

:: Run Flask app
python app.py

pause
