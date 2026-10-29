@echo off
title Jarvis AI Assistant
cd /d "%~dp0"
echo Starting Jarvis AI with Holographic Video Interface...
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Jarvis exited with code %ERRORLEVEL%.
    pause
)
