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
echo  [6] Start packaged Windows EXE
echo.
choice /c 123456 /n /m "Select an option: "
if errorlevel 6 goto packaged
if errorlevel 5 goto folder
if errorlevel 4 goto backend
if errorlevel 3 goto both
if errorlevel 2 goto web
if errorlevel 1 goto desktop
:desktop
where py >nul 2>nul
if not errorlevel 1 (
  py apps\windows\quantnex_desktop.py
  goto end
)
if exist "dist\QUANTNEX.exe" (
  echo Python was not found. Starting the packaged EXE instead.
  start "" "dist\QUANTNEX.exe"
  goto end
)
echo Python launcher and packaged EXE were not found. Install Python 3.11+ or download the Windows build.
pause
exit /b 1
:packaged
if exist "dist\QUANTNEX.exe" (
  start "" "dist\QUANTNEX.exe"
) else (
  echo Packaged EXE not found. Run option 1 to start the source version.
  pause
)
goto end
:web
start "QUANTNEX Web Server" cmd /k py apps\web\local_server.py
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:5500
goto end
:both
start "QUANTNEX Web Server" cmd /k py apps\web\local_server.py
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:5500
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
