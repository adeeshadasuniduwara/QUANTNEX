@echo off
setlocal
title QUANTNEX Launcher
cd /d "%~dp0"
echo.
echo  =========================================
echo             QUANTNEX WORKSPACE
echo  =========================================
echo.
echo  [1] Start Windows Desktop
echo  [2] Start Web Workspace
echo  [3] Start Desktop + Web
echo  [4] Start Local Backend API
echo  [5] Open Web folder
echo.
choice /c 12345 /n /m "Select an option: "
if errorlevel 5 goto folder
if errorlevel 4 goto backend
if errorlevel 3 goto both
if errorlevel 2 goto web
if errorlevel 1 goto desktop
:desktop
if exist "dist\QUANTNEX.exe" (
  start "" "dist\QUANTNEX.exe"
  goto end
)
where py >nul 2>nul
if errorlevel 1 (echo Python launcher not found. Install Python 3.11+ and try again.&pause&exit /b 1)
py apps\windows\quantnex_desktop.py
goto end
:web
start "" http://127.0.0.1:5500
py -m http.server 5500 --directory apps\web
goto end
:both
start "" http://127.0.0.1:5500
start "QUANTNEX Web Server" cmd /k py -m http.server 5500 --directory apps\web
py apps\windows\quantnex_desktop.py
goto end
:backend
call run_backend.bat
goto end
:folder
start "" "%~dp0apps\web"
goto end
:end
endlocal
