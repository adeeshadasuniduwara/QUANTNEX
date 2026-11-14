@echo off
setlocal EnableExtensions
title QUANTNEX Web + Backend Launcher
cd /d "%~dp0"

echo.
echo  =========================================
echo             QUANTNEX WORKSPACE
echo  =========================================
echo.
echo  [1] Start Web + Backend + Auto Updates
echo  [2] Start Backend API only
echo  [3] Open Web source folder
echo.
choice /c 123 /n /m "Select an option: "
if errorlevel 3 goto folder
if errorlevel 2 goto backend
if errorlevel 1 goto web

:web
echo.
echo Starting QUANTNEX Web + Backend supervisor...
where py >nul 2>nul
if not errorlevel 1 (
  py -3 run_quantnex_services.py
  set "APP_EXIT=%ERRORLEVEL%"
) else (
  where python >nul 2>nul
  if errorlevel 1 goto python_missing
  python run_quantnex_services.py
  set "APP_EXIT=%ERRORLEVEL%"
)
if not "%APP_EXIT%"=="0" goto failed
goto end

:backend
echo.
echo Starting QUANTNEX Backend API only...
call run_backend.bat
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" goto failed
goto end

:folder
echo.
echo This opens source files only. It does not start the API or live feeds.
start "" "%~dp0apps\web"
goto end

:python_missing
echo.
echo ERROR: Python 3.11 or newer was not found.
echo Install Python from https://www.python.org/downloads/ and enable Add Python to PATH.
goto failed

:failed
echo.
echo =========================================
echo QUANTNEX did not start successfully.
echo The error is shown above.
echo =========================================
echo.
echo If the full launcher started, diagnostic log:
echo %~dp0logs\launcher.log
echo.
echo This window will stay open. Copy the error above before closing it.
pause
exit /b 1

:end
endlocal
