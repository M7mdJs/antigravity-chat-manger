@echo off
title Antigravity Chat Manager
cd /d "%~dp0"

echo Starting Antigravity Chat Manager GUI...
python main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] An error occurred while launching.
    pause
)
