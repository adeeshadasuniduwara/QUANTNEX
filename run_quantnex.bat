@echo off
setlocal
title QUANTNEX Launcher
cd /d "%~dp0"
echo.
echo  =========================================
echo             QUANTNEX WORKSPACE
echo  =========================================
echo.
echo  [1] Start Windows Desktop + Auto Updates
echo  [2] Start Web + Backend (ONE CMD)
echo  [3] Start Desktop + Web + Backend (ONE CMD)
echo  [4] Start Local Backend API only
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
  py run_quantnex_services.py --desktop
  goto end
)
python run_quantnex_services.py --desktop
goto end

:packaged
if exist "dist\QUANTNEX.exe" (
  start "" "dist\QUANTNEX.exe"
) else (
  echo Packaged EXE not found. Run option 1 to start the source version.
  pause
)
goto end

:web
where py >nul 2>nul
if not errorlevel 1 (
  py run_quantnex_services.py
) else (
  python run_quantnex_services.py
)
goto end

:both
where py >nul 2>nul
if not errorlevel 1 (
  py run_quantnex_services.py --desktop
) else (
  python run_quantnex_services.py --desktop
)
goto end

:backend
call run_backend.bat
goto end

:folder
start "" "%~dp0apps\web"
goto end

:end
endlocal
