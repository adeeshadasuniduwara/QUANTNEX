"""Run QUANTNEX services and supervise safe automatic GitHub source updates."""
from __future__ import annotations

import argparse
import os
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
UPDATE_INTERVAL_SECONDS = 300


def run_checked(command: list[str], cwd: Path, label: str) -> None:
    print(f"\n[SETUP] {label}", flush=True)
    result = subprocess.run(command, cwd=cwd)
    if result.returncode:
        raise RuntimeError(f"{label} failed with exit code {result.returncode}.")


def prepare_backend() -> Path:
    if not VENV_PYTHON.exists():
        run_checked([sys.executable, "-m", "venv", str(BACKEND / ".venv")], BACKEND, "Create backend virtual environment")
    print("\n[SETUP] Check backend dependencies", flush=True)
    run_checked([str(VENV_PYTHON), "-m", "pip", "install", "-r", "requirements.txt"], BACKEND, "Install/check backend dependencies")
    run_checked([str(VENV_PYTHON), "bootstrap.py"], BACKEND, "Run automatic configuration and startup diagnostics")
    return VENV_PYTHON


def stream_output(name: str, process: subprocess.Popen) -> None:
    assert process.stdout is not None
    for line in iter(process.stdout.readline, ""):
        print(f"[{name}] {line.rstrip()}", flush=True)
    process.stdout.close()


def start_process(name: str, command: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.Popen:
    process = subprocess.Popen(
        command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=CREATE_NO_WINDOW,
    )
    PROCESSES.append((name, process))
    threading.Thread(target=stream_output, args=(name, process), daemon=True).start()
    return process


def wait_for_url(url: str, label: str, process: subprocess.Popen, timeout: float = 45.0) -> None:
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
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
    PROCESSES.clear()


def check_for_automatic_update() -> bool:
    try:
        from quantnex_updater import check_and_apply
        result = check_and_apply(ROOT)
        if result["status"] == "updated":
            print("\n[AUTO UPDATE] " + result["message"], flush=True)
            print("[AUTO UPDATE] Installed " + result["version"], flush=True)
            for path in result["changed_files"][:20]:
                print("[AUTO UPDATE] " + path, flush=True)
            return bool(result.get("restart_required"))
        if result["status"] == "baseline":
            print("[AUTO UPDATE] Installed source baseline recorded: " + result["version"], flush=True)
        elif result["status"] == "current":
            print("[AUTO UPDATE] QUANTNEX is up to date: " + result["version"], flush=True)
        return False
    except Exception as exc:
        print(f"[AUTO UPDATE] Check deferred; existing QUANTNEX will keep running: {exc}", flush=True)
        return False


def restart_launcher() -> None:
    os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--desktop", action="store_true", help="Also launch the Windows desktop app.")
    args = parser.parse_args()
    try:
        print("==============================================", flush=True)
        print("             QUANTNEX WORKSPACE", flush=True)
        print("==============================================", flush=True)

        if check_for_automatic_update():
            print("[AUTO UPDATE] Restarting launcher with the new source…", flush=True)
            restart_launcher()

        try:
            python = prepare_backend()
            api = start_process("API", [str(python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--log-level", "info"], BACKEND)
            web_env = os.environ.copy()
            web_env["QUANTNEX_SUPERVISED"] = "1"
            web = start_process("WEB", [sys.executable, str(WEB_SERVER)], ROOT, env=web_env)
            if args.desktop:
                start_process("DESKTOP", [str(python), str(ROOT / "apps" / "windows" / "quantnex_desktop.py")], ROOT)

            wait_for_url("http://127.0.0.1:8000/health", "Backend API · http://127.0.0.1:8000", api)
            wait_for_url("http://127.0.0.1:5500/", "Web workspace · http://127.0.0.1:5500", web)
        except Exception:
            # A newly applied source revision is not trusted until both local
            # services pass their startup health checks. Restore the last known
            # working files before retrying, without touching user data.
            stop_all()
            try:
                from quantnex_updater import rollback_last_update
                if rollback_last_update(ROOT):
                    print("[AUTO UPDATE] New source failed startup health checks; restored the previous version.", flush=True)
                    restart_launcher()
            except Exception as rollback_error:
                print(f"[AUTO UPDATE] Automatic rollback could not complete: {rollback_error}", flush=True)
            raise

        try:
            from quantnex_updater import confirm_update
            if confirm_update(ROOT):
                print("[AUTO UPDATE] Startup health checks passed; rollback checkpoint confirmed.", flush=True)
        except Exception as confirm_error:
            print(f"[AUTO UPDATE] Startup confirmation deferred: {confirm_error}", flush=True)
        webbrowser.open("http://127.0.0.1:5500/")
        print("\nQUANTNEX is running. Keep this single CMD window open.", flush=True)
        print("Automatic GitHub update checks run every 5 minutes. Updated source restarts services automatically.", flush=True)
        print("Press CTRL+C once to stop the API, Web server and optional Desktop app.", flush=True)

        next_update_check = time.monotonic() + UPDATE_INTERVAL_SECONDS
        while True:
            for name, process in PROCESSES:
                code = process.poll()
                if code is not None:
                    raise RuntimeError(f"{name} stopped unexpectedly (exit code {code}). See its output above.")
            if time.monotonic() >= next_update_check:
                if check_for_automatic_update():
                    print("\n[AUTO UPDATE] Stopping services safely before restart…", flush=True)
                    stop_all()
                    restart_launcher()
                next_update_check = time.monotonic() + UPDATE_INTERVAL_SECONDS
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
