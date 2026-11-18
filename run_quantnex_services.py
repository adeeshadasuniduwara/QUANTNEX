"""Run the QUANTNEX local Backend + Web workspace and supervise source updates."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
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
VENV_DIR = BACKEND / ".venv"
VENV_PYTHON = VENV_DIR / (Path("Scripts") / "python.exe" if os.name == "nt" else Path("bin") / "python")
LOG_FILE = ROOT / "logs" / "launcher.log"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PROCESSES: list[tuple[str, subprocess.Popen]] = []
UPDATE_INTERVAL_SECONDS = 300
UPDATE_REQUEST_FILE = ROOT / "data" / "updates" / "check_requested.json"
UPDATE_PROGRESS_FILE = ROOT / "data" / "updates" / "check_in_progress.json"
UPDATE_ERROR_FILE = ROOT / "data" / "updates" / "check_error.json"
UPDATE_ROLLBACK_MARKER = ROOT / "data" / "updates" / "last_update.json"


class Tee:
    """Write launcher output to both the console and a persistent diagnostic log."""
    def __init__(self, *streams):
        self.streams = streams

    def write(self, value: str) -> int:
        for stream in self.streams:
            stream.write(value)
            stream.flush()
        return len(value)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


def configure_logging() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > 2 * 1024 * 1024:
        backup = LOG_FILE.with_suffix(".log.old")
        try:
            backup.unlink(missing_ok=True)
            LOG_FILE.replace(backup)
        except OSError:
            pass
    log_stream = LOG_FILE.open("a", encoding="utf-8", buffering=1)
    sys.stdout = Tee(sys.__stdout__, log_stream)
    sys.stderr = Tee(sys.__stderr__, log_stream)
    print("\n" + "=" * 62, flush=True)
    print("QUANTNEX launcher started · " + time.strftime("%Y-%m-%d %H:%M:%S"), flush=True)
    print("Diagnostic log: " + str(LOG_FILE), flush=True)


def run_checked(command: list[str], cwd: Path, label: str) -> None:
    print(f"\\n[SETUP] {label}", flush=True)
    print("[COMMAND] " + subprocess.list2cmdline(command), flush=True)
    try:
        # Replay child output through Tee so pip/venv/bootstrap diagnostics are
        # captured in launcher.log as well as shown in the console.
        result = subprocess.run(
            command, cwd=cwd, check=False, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        raise RuntimeError(f"{label} could not run: {exc}") from exc
    if result.stdout:
        print(result.stdout.rstrip(), flush=True)
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr, flush=True)
    if result.returncode:
        raise RuntimeError(
            f"{label} failed with exit code {result.returncode}. "
            f"Full command output is recorded in {LOG_FILE}."
        )

def prepare_backend() -> Path:
    """Create or repair an isolated backend environment and install dependencies."""
    if sys.version_info < (3, 11):
        raise RuntimeError(
            f"Python 3.11 or newer is required; launcher selected {sys.version.split()[0]}. "
            "Install Python 3.12 or 3.14 and retry."
        )
    if not BACKEND.is_dir():
        raise RuntimeError(f"Backend source folder is missing: {BACKEND}")
    if not (BACKEND / "requirements.txt").is_file():
        raise RuntimeError(f"Backend dependency file is missing: {BACKEND / 'requirements.txt'}")

    # A cancelled first install can leave a half-created venv. Rebuild only
    # this generated environment folder; never touch user data or databases.
    if VENV_DIR.exists() and not VENV_PYTHON.is_file():
        print(f"[SETUP] Repairing incomplete virtual environment: {VENV_DIR}", flush=True)
        shutil.rmtree(VENV_DIR)
    if not VENV_PYTHON.is_file():
        run_checked([sys.executable, "-m", "venv", str(VENV_DIR)],
                    BACKEND, "Create backend virtual environment")
    if not VENV_PYTHON.is_file():
        raise RuntimeError(f"Python environment creation did not produce: {VENV_PYTHON}")
    print("\\n[SETUP] Check backend dependencies (retry enabled; first run may take a few minutes)", flush=True)
    run_checked(
        [str(VENV_PYTHON), "-m", "pip", "install", "--disable-pip-version-check",
         "--retries", "3", "--timeout", "30", "-r", "requirements.txt"],
        BACKEND, "Install/check backend dependencies",
    )
    run_checked([str(VENV_PYTHON), "bootstrap.py"], BACKEND,
                "Run automatic configuration and startup diagnostics")
    return VENV_PYTHON

def stream_output(name: str, process: subprocess.Popen) -> None:
    assert process.stdout is not None
    for line in iter(process.stdout.readline, ""):
        print(f"[{name}] {line.rstrip()}", flush=True)
    process.stdout.close()


def start_process(name: str, command: list[str], cwd: Path,
                  env: dict[str, str] | None = None) -> subprocess.Popen:
    process = subprocess.Popen(
        command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=CREATE_NO_WINDOW,
    )
    PROCESSES.append((name, process))
    threading.Thread(target=stream_output, args=(name, process), daemon=True).start()
    return process


def wait_for_url(url: str, label: str, process: subprocess.Popen,
                 timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not ready"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{label} exited early (code {process.returncode}). Check {LOG_FILE}.")
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if 200 <= response.status < 300:
                    print(f"[READY] {label}", flush=True)
                    return
                last_error = f"HTTP {response.status}"
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"{label} did not become ready within {timeout:.0f}s: {last_error}")


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
                process.wait(timeout=3)
    PROCESSES.clear()


def check_for_automatic_update(force_reconcile: bool = False) -> bool:
    try:
        from quantnex_updater import check_and_apply
        result = check_and_apply(ROOT, force_reconcile=force_reconcile)
        if result["status"] == "updated":
            print("\n[AUTO UPDATE] " + result["message"], flush=True)
            print("[AUTO UPDATE] Installed " + result["version"], flush=True)
            for path in result["changed_files"][:30]:
                print("[AUTO UPDATE] " + path, flush=True)
            restart_required = bool(result.get("restart_required"))
            if not restart_required:
                UPDATE_PROGRESS_FILE.unlink(missing_ok=True)
            UPDATE_ERROR_FILE.unlink(missing_ok=True)
            if restart_required:
                # The currently running (pre-update) launcher must pass this through
                # its default inherited environment to the newly installed launcher.
                os.environ["QUANTNEX_SUPPRESS_BROWSER_OPEN"] = "1"
            return restart_required
        if result["status"] == "baseline":
            print("[AUTO UPDATE] Installed source baseline recorded: " + result["version"], flush=True)
        elif result["status"] == "current":
            print("[AUTO UPDATE] QUANTNEX is up to date: " + result["version"], flush=True)
        UPDATE_PROGRESS_FILE.unlink(missing_ok=True)
        UPDATE_ERROR_FILE.unlink(missing_ok=True)
        return False
    except Exception as exc:
        print(f"[AUTO UPDATE] Check deferred; existing QUANTNEX will keep running: {type(exc).__name__}: {exc}", flush=True)
        if force_reconcile:
            import json
            UPDATE_PROGRESS_FILE.unlink(missing_ok=True)
            UPDATE_ERROR_FILE.parent.mkdir(parents=True, exist_ok=True)
            UPDATE_ERROR_FILE.write_text(json.dumps({"message": str(exc)[:500]}), encoding="utf-8")
        return False


def consume_manual_update_request() -> bool:
    """Move a browser request into a visible in-progress marker for the UI watcher."""
    try:
        if not UPDATE_REQUEST_FILE.is_file():
            return False
        UPDATE_REQUEST_FILE.unlink()
        UPDATE_PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        UPDATE_PROGRESS_FILE.write_text(
            '{"status":"checking","message":"Checking and repairing the complete local source snapshot…"}',
            encoding="utf-8",
        )
        UPDATE_ERROR_FILE.unlink(missing_ok=True)
        return True
    except OSError as exc:
        print(f"[AUTO UPDATE] Could not consume the manual check request: {exc}", flush=True)
        return False


def restart_launcher() -> None:
    """Restart safely on Windows even when the workspace path contains spaces.

    Do not use os.execv here: Windows command-line reconstruction can mishandle
    script paths with spaces in some Python launcher/runtime combinations.
    Popen receives an argv list (not a shell command string), preserving the
    complete script path as one argument.
    """
    script = Path(__file__).resolve()
    command = [sys.executable, str(script)]
    restart_env = os.environ.copy()
    # A source-update restart must reconnect the already-open browser tab, not spawn another one.
    restart_env["QUANTNEX_SUPPRESS_BROWSER_OPEN"] = "1"
    print("[RESTART] Python: " + sys.executable, flush=True)
    print("[RESTART] Script: " + str(script), flush=True)
    try:
        subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdin=None,
            stdout=None,
            stderr=None,
            close_fds=False,
            creationflags=0,
            env=restart_env,
        )
    except OSError as exc:
        raise RuntimeError(
            f"Could not restart QUANTNEX from '{script}': {type(exc).__name__}: {exc}"
        ) from exc
    raise SystemExit(0)


def consume_browser_open_suppression() -> bool:
    """Consume the one-shot flag used only for update/rollback restarts."""
    return os.environ.pop("QUANTNEX_SUPPRESS_BROWSER_OPEN", "") == "1"


def pending_source_update_restart() -> bool:
    """Detect the first launch after an updater install, even from an older launcher."""
    return UPDATE_ROLLBACK_MARKER.is_file()


def main() -> int:
    configure_logging()
    suppress_browser_open = consume_browser_open_suppression() or pending_source_update_restart()
    try:
        print("==============================================", flush=True)
        print("             QUANTNEX WEB WORKSPACE", flush=True)
        print("==============================================", flush=True)

        if check_for_automatic_update():
            print("[AUTO UPDATE] Restarting launcher with the new source…", flush=True)
            restart_launcher()

        api = web = None
        try:
            python = prepare_backend()
            api = start_process(
                "API",
                [str(python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                 "--port", "8000", "--log-level", "info"],
                BACKEND,
            )
            web_env = os.environ.copy()
            web_env["QUANTNEX_SUPERVISED"] = "1"
            web = start_process("WEB", [sys.executable, str(WEB_SERVER)], ROOT, env=web_env)

            wait_for_url("http://127.0.0.1:8000/health",
                         "Backend API · http://127.0.0.1:8000", api)
            wait_for_url("http://127.0.0.1:5500/",
                         "Web workspace · http://127.0.0.1:5500", web)
        except Exception:
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
                UPDATE_PROGRESS_FILE.unlink(missing_ok=True)
                UPDATE_ERROR_FILE.unlink(missing_ok=True)
        except Exception as confirm_error:
            print(f"[AUTO UPDATE] Startup confirmation deferred: {confirm_error}", flush=True)

        if suppress_browser_open:
            print("[BROWSER] Update restart detected; keeping the existing browser tab open.", flush=True)
        else:
            webbrowser.open("http://127.0.0.1:5500/")
        print("\nQUANTNEX Web + Backend are running.", flush=True)
        print("Keep this CMD window open. Do not close it while using the workspace.", flush=True)
        print("Automatic GitHub source checks run every 5 minutes.", flush=True)
        print("Press CTRL+C once to stop both services.", flush=True)

        next_update_check = time.monotonic() + UPDATE_INTERVAL_SECONDS
        while True:
            for name, process in PROCESSES:
                code = process.poll()
                if code is not None:
                    raise RuntimeError(f"{name} stopped unexpectedly (exit code {code}). See {LOG_FILE}.")
            manual_check_requested = consume_manual_update_request()
            scheduled_check_due = time.monotonic() >= next_update_check
            if manual_check_requested or scheduled_check_due:
                if manual_check_requested:
                    print("\n[AUTO UPDATE] Manual Check for Updates request received.", flush=True)
                if check_for_automatic_update(force_reconcile=manual_check_requested):
                    print("\n[AUTO UPDATE] Stopping services safely before restart…", flush=True)
                    stop_all()
                    restart_launcher()
                next_update_check = time.monotonic() + UPDATE_INTERVAL_SECONDS
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping QUANTNEX services…", flush=True)
        return 0
    except Exception as exc:
        print(f"\nQUANTNEX STARTUP ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        print("The launcher will remain open so this error can be read.", file=sys.stderr, flush=True)
        print("Check the diagnostic log: " + str(LOG_FILE), file=sys.stderr, flush=True)
        return 1
    finally:
        stop_all()


if __name__ == "__main__":
    raise SystemExit(main())
