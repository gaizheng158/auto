@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Auto Study Launcher

echo.
echo ========================================
echo  Auto Study Launcher
echo ========================================
echo.

if not exist main.py (
    echo [ERROR] main.py not found.
    echo Please unzip the package first, then run this bat file.
    echo.
    pause
    exit /b 1
)

set "PYTHON_CMD="
python --version >nul 2>nul
if %errorlevel%==0 set "PYTHON_CMD=python"

if not defined PYTHON_CMD (
    py -3 --version >nul 2>nul
    if %errorlevel%==0 set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
    echo [ERROR] Python was not found on this computer.
    echo Install Python first, and tick "Add Python to PATH".
    echo Download: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo [1/3] Python command: %PYTHON_CMD%
echo [2/3] Installing/checking dependencies...
%PYTHON_CMD% -m pip install selenium webdriver-manager -q
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install dependencies.
    echo Possible reasons: network blocked, pip missing, or Python is incomplete.
    echo Please take a screenshot of this window and send it back.
    echo.
    pause
    exit /b 1
)

echo [3/3] Starting main program...
echo.
%PYTHON_CMD% main.py
if errorlevel 1 (
    echo.
    echo [ERROR] Program exited with an error. See messages above.
)

echo.
pause
