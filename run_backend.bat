@echo off
setlocal
title QUANTNEX Backend API
cd /d "%~dp0backend"
where py >nul 2>nul
if errorlevel 1 (echo Python 3.11+ is required.&pause&exit /b 1)
if not exist ".venv\Scripts\python.exe" py -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
if not exist ".env" (
  copy .env.example .env >nul
  echo.
  echo IMPORTANT: Edit backend\.env and set QUANTNEX_SECRET_KEY before using accounts.
  echo This development server binds only to 127.0.0.1.
  pause
)
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
endlocal
