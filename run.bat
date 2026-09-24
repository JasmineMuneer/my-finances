@echo off
echo ============================================================
echo  My Finances — Starting up...
echo ============================================================

REM Force UTF-8 output in the terminal so ₹ renders correctly
chcp 65001 > nul

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python from https://python.org and try again.
    pause
    exit /b 1
)

REM Create virtual environment if it doesn't exist
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate venv and install/upgrade requirements
echo Installing requirements...
call venv\Scripts\activate.bat
pip install -q flask --upgrade

REM Set Python to always use UTF-8 (critical for ₹ on Windows)
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

REM Start the app and open the browser
echo.
echo Starting My Finances at http://127.0.0.1:5000
echo Press Ctrl+C to stop the server.
echo.
start "" http://127.0.0.1:5000
python app.py

pause
