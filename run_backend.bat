@echo off
setlocal
title QUANTNEX Backend API
cd /d "%~dp0backend"

where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.11+ is required. Install Python and enable the Python Launcher.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating QUANTNEX Python environment...
  py -m venv .venv
  if errorlevel 1 (
    echo ERROR: Could not create the Python virtual environment.
    pause
    exit /b 1
  )
)

call .venv\Scripts\activate.bat
if errorlevel 1 (
  echo ERROR: Could not activate the QUANTNEX Python environment.
  pause
  exit /b 1
)

echo.
echo Installing/checking QUANTNEX backend dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo ERROR: Dependency installation failed. The API was not started.
  echo Psycopg is configured to resolve an available compatible 3.2.x binary release.
  echo Check your internet connection, then run this launcher again.
  echo If the error persists, copy the complete pip error for diagnosis.
  pause
  exit /b 1
)

if not exist ".env" (
  copy .env.example .env >nul
  echo.
  echo IMPORTANT: Edit backend\.env and set QUANTNEX_SECRET_KEY before using accounts.
  echo This development server binds only to 127.0.0.1.
  pause
)

echo.
echo Starting QUANTNEX Backend API...
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
endlocal
