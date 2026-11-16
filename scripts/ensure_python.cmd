@echo off
rem Resolve a real Python 3.11+ interpreter; ignore the Microsoft Store execution-alias stub.
set "QUANTNEX_PYTHON="

where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
  if not errorlevel 1 (
    set "QUANTNEX_PYTHON=py -3"
    goto :eof
  )
)

where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
  if not errorlevel 1 (
    set "QUANTNEX_PYTHON=python"
    goto :eof
  )
)

rem Check common per-user install locations even when PATH was not refreshed.
if exist "%LocalAppData%\Programs\Python\Python314\python.exe" (
  set "QUANTNEX_PYTHON=%LocalAppData%\Programs\Python\Python314\python.exe"
  goto :eof
)
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
  set "QUANTNEX_PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"
  goto :eof
)
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
  set "QUANTNEX_PYTHON=%LocalAppData%\Programs\Python\Python311\python.exe"
  goto :eof
)

echo.
echo Python 3.11 or newer was not found. QUANTNEX needs Python to start.
where winget >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.12 from https://www.python.org/downloads/windows/
  echo During setup, enable the Python launcher or Add Python to PATH.
  exit /b 1
)
choice /c YN /n /m "Install Python 3.12 automatically using Windows Package Manager? [Y/N]: "
if errorlevel 2 exit /b 1
echo.
winget install --id Python.Python.3.12 --exact --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
  echo Python installation did not complete. Install it manually, then retry.
  exit /b 1
)

rem Re-check after install; py launcher is preferred and does not depend on PATH refresh.
where py >nul 2>nul
if not errorlevel 1 (
  py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
  if not errorlevel 1 (
    set "QUANTNEX_PYTHON=py -3.12"
    goto :eof
  )
)
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
  set "QUANTNEX_PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"
  goto :eof
)
echo Python was installed, but this CMD session cannot locate it yet.
echo Close this window, open QUANTNEX again, and retry.
exit /b 1
