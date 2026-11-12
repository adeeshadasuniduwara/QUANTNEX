"""Run QUANTNEX API and Web updater under one visible Windows CMD window."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
WEB_SERVER = ROOT / "apps" / "web" / "quantnex_local_server.py"
VENV_PYTHON = BACKEND / ".venv" / "Scripts" / "python.exe"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PROCESSES: list[tuple[str, subprocess.Popen]] = []


def run_checked(command: list[str], cwd: Path, label: str) -> None:
    print(f"\n[SETUP] {label}", flush=True)
    result = subprocess.run(command, cwd=cwd)
    if result.returncode:
        raise RuntimeError(f"{label} failed with exit code {result.returncode}.")


def prepare_backend() -> Path:
    if not VENV_PYTHON.exists():
        run_checked([sys.executable, "-m", "venv", str(BACKEND / ".venv")], BACKEND, "Create backend virtual environment")
    print("\n[SETUP] Update pip (optional)", flush=True)
    pip_update = subprocess.run([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip"], cwd=BACKEND)
    if pip_update.returncode:
        print("[WARNING] pip could not update; continuing with the installed pip version.", flush=True)
    run_checked([str(VENV_PYTHON), "-m", "pip", "install", "-r", "requirements.txt"], BACKEND, "Install/check backend dependencies")
    run_checked([str(VENV_PYTHON), "bootstrap.py"], BACKEND, "Run automatic configuration and startup diagnostics")
    return VENV_PYTHON


def stream_output(name: str, process: subprocess.Popen) -> None:
    assert process.stdout is not None
    for line in iter(process.stdout.readline, ""):
        print(f"[{name}] {line.rstrip()}", flush=True)
    process.stdout.close()


def start_process(name: str, command: list[str], cwd: Path) -> subprocess.Popen:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=CREATE_NO_WINDOW,
    )
    PROCESSES.append((name, process))
    threading.Thread(target=stream_output, args=(name, process), daemon=True).start()
    return process


def wait_for_url(url: str, label: str, process: subprocess.Popen, timeout: float = 35.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not ready"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{label} exited early (code {process.returncode}). See the log lines above.")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    print(f"[READY] {label}", flush=True)
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"{label} did not become ready in time: {last_error}")


def stop_all() -> None:
    for _, process in reversed(PROCESSES):
        if process.poll() is None:
            process.terminate()
    for _, process in reversed(PROCESSES):
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--desktop", action="store_true", help="Also launch the Windows desktop app.")
    args = parser.parse_args()
    try:
        print("==============================================", flush=True)
        print("             QUANTNEX WORKSPACE", flush=True)
        print("==============================================", flush=True)
        python = prepare_backend()

        api = start_process("API", [str(python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--log-level", "info"], BACKEND)
        web = start_process("WEB", [sys.executable, str(WEB_SERVER)], ROOT)
        if args.desktop:
            start_process("DESKTOP", [sys.executable, str(ROOT / "apps" / "windows" / "quantnex_desktop.py")], ROOT)

        wait_for_url("http://127.0.0.1:8000/health", "Backend API · http://127.0.0.1:8000", api)
        wait_for_url("http://127.0.0.1:5500/", "Web workspace · http://127.0.0.1:5500", web)
        webbrowser.open("http://127.0.0.1:5500/")
        print("\nQUANTNEX is running. Keep this single CMD window open.", flush=True)
        print("Press CTRL+C once to stop the API, Web server and optional Desktop app.", flush=True)

        while True:
            for name, process in PROCESSES:
                code = process.poll()
                if code is not None:
                    raise RuntimeError(f"{name} stopped unexpectedly (exit code {code}). See its output above.")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping QUANTNEX services…", flush=True)
        return 0
    except Exception as exc:
        print(f"\nQUANTNEX STARTUP ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        stop_all()


if __name__ == "__main__":
    raise SystemExit(main())
