@echo off
setlocal
title QUANTNEX Backend API
cd /d "%~dp0"

if not exist "backend\.venv\Scripts\python.exe" (
  echo Checking Python installation...
  call "%~dp0scripts\ensure_python.cmd"
  if errorlevel 1 goto failed
  echo Creating QUANTNEX Python environment...
  %QUANTNEX_PYTHON% -m venv "backend\.venv"
  if errorlevel 1 (
    echo ERROR: Could not create the Python virtual environment.
    goto failed
  )
)

cd /d "%~dp0backend"
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
