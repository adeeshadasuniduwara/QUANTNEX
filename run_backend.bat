@echo off
setlocal
title QUANTNEX Backend API
cd /d "%~dp0backend"

if not exist ".venv\Scripts\python.exe" (
  echo Creating QUANTNEX Python environment...
  where py >nul 2>nul
  if not errorlevel 1 (
    py -m venv .venv
  ) else (
    python -m venv .venv
  )
  if errorlevel 1 (
    echo ERROR: Could not create the Python virtual environment.
    goto failed
  )
)

echo.
echo Updating pip and checking backend dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: Dependency installation failed. API startup cancelled.
  goto failed
)

echo.
echo Running QUANTNEX automatic startup diagnostics...
.venv\Scripts\python.exe bootstrap.py
if errorlevel 1 goto failed

echo.
echo Starting QUANTNEX Backend API at http://127.0.0.1:8000
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info
if errorlevel 1 goto failed
goto end

:failed
echo.
echo QUANTNEX backend did not start. Read the diagnostic above.
if not "%QUANTNEX_NO_PAUSE%"=="1" pause
exit /b 1

:end
endlocal
