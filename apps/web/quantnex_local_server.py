"""Loopback-only Web server with a pinned-commit GitHub source updater."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import threading
import urllib.request
import zipfile
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent.parent
DATA = ROOT / "data"
VERSION_FILE = DATA / "quantnex_web_version.json"
SOURCE_STATE_FILE = DATA / "quantnex_update_state.json"
SUPERVISOR_CHECK_FILE = DATA / "updates" / "check_requested.json"
REPO = "adeeshadasuniduwara/QUANTNEX"
BRANCH = "main"
HOST, PORT = "127.0.0.1", 5500
LOCK = threading.Lock()
STATE = {"status": "idle", "message": ""}


def installed_revision() -> str:
    # Prefer the Web updater marker, then the full-source supervisor marker.
    # ZIP installs managed by run_quantnex_services.py do not create the legacy Web-only marker.
    for marker in (VERSION_FILE, SOURCE_STATE_FILE):
        try:
            value = json.loads(marker.read_text(encoding="utf-8")).get("commit_sha", "")
            if re.fullmatch(r"[0-9a-f]{40}", str(value)):
                return value
        except (OSError, ValueError, AttributeError):
            continue
    return ""


def supervisor_update_status() -> dict:
    """Report the real full-source revision instead of placeholder version labels."""
    installed = ""
    try:
        state = json.loads(SOURCE_STATE_FILE.read_text(encoding="utf-8"))
        candidate = str(state.get("commit_sha", ""))
        if re.fullmatch(r"[0-9a-f]{40}", candidate):
            installed = candidate
    except (OSError, ValueError, AttributeError):
        pass
    latest = latest_commit()
    details = update_summary(installed, latest) if installed else {
        "changes": [latest["message"]] if latest.get("message") else [],
        "files_changed": 0,
        "commits_behind": 1,
    }
    update_available = not installed or installed != latest["sha"]
    return {
        "installed": "main@" + installed[:7] if installed else "Initial source sync pending",
        "latest": "main@" + latest["sha"][:7],
        "latest_message": latest["message"],
        "update_available": update_available,
        "managed_by_supervisor": True,
        "release_notes": latest["html_url"],
        "commit_sha": latest["sha"],
        **details,
        "message": (
            "A source update is available. The QUANTNEX supervisor will install it and restart the services safely."
            if update_available else
            "QUANTNEX source is up to date. Automatic checks continue every five minutes."
        ),
    }


def queue_supervisor_check() -> None:
    """Ask the running launcher to perform an immediate safe source check."""
    SUPERVISOR_CHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = SUPERVISOR_CHECK_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps({"requested_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    temporary.replace(SUPERVISOR_CHECK_FILE)


def github_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "QUANTNEX-Web-Updater",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub returned an invalid update response.")
    return payload


def latest_commit() -> dict:
    commit = github_json(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}")
    sha = str(commit.get("sha", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("GitHub did not return a valid source commit.")
    message = str(commit.get("commit", {}).get("message", "")).splitlines()[0][:160]
    return {
        "sha": sha,
        "message": message,
        "html_url": commit.get("html_url", f"https://github.com/{REPO}/commits/{BRANCH}"),
        "archive_url": f"https://codeload.github.com/{REPO}/zip/{sha}",
    }


def update_summary(installed: str, latest: dict) -> dict:
    """Return concise, safe release details from GitHub's compare endpoint."""
    changes = []
    files_changed = 0
    commits_behind = 1
    if re.fullmatch(r"[0-9a-f]{40}", installed):
        try:
            comparison = github_json(
                f"https://api.github.com/repos/{REPO}/compare/{installed}...{latest['sha']}"
            )
            commits = comparison.get("commits", [])
            commits_behind = int(comparison.get("ahead_by", len(commits)))
            files_changed = len(comparison.get("files", []))
            for item in commits[-8:]:
                message = str(item.get("commit", {}).get("message", "")).strip()
                headline = message.splitlines()[0][:140] if message else ""
                if headline and headline not in changes:
                    changes.append(headline)
        except Exception:
            # A compare failure must never prevent a valid update from being offered.
            pass
    if not changes and latest.get("message"):
        changes.append(str(latest["message"])[:140])
    return {
        "changes": changes[:8],
        "files_changed": files_changed,
        "commits_behind": commits_behind,
    }


def _safe_web_relative(raw_parts: tuple[str, ...]) -> PurePosixPath | None:
    """Validate archive-relative names before creating Windows-native Paths."""
    raw = "/".join(raw_parts)
    if not raw or any(char in raw for char in ("\\", ":", "\x00")):
        return None
    relative = PurePosixPath(raw)
    if relative.is_absolute() or not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        return None
    return relative


def _safe_web_destination(relative: PurePosixPath) -> Path:
    """Resolve a Web update target and reject existing symlink escapes."""
    base = WEB.resolve()
    try:
        destination = (base / Path(*relative.parts)).resolve()
        destination.relative_to(base)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError("The Web update destination escapes the workspace.") from exc
    if destination == base:
        raise RuntimeError("The Web update cannot replace the workspace root.")
    return destination


MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


def download_bounded_archive(request, destination: Path, max_bytes: int = MAX_ARCHIVE_BYTES) -> int:
    """Download a pinned source archive with a strict compressed-size limit."""
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    advertised = int(content_length)
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("The update archive has an invalid Content-Length.") from exc
                if advertised < 0 or advertised > max_bytes:
                    raise RuntimeError("The update archive exceeds the 100 MB download limit.")
            with destination.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise RuntimeError("The update archive exceeds the 100 MB download limit.")
                    output.write(chunk)
        if total == 0:
            raise RuntimeError("The update archive is empty.")
        return total
    except Exception:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def install_commit(commit: dict) -> None:
    sha = str(commit.get("sha", ""))
    archive_url = str(commit.get("archive_url", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or archive_url != f"https://codeload.github.com/{REPO}/zip/{sha}":
        raise RuntimeError("The update source did not pass commit URL validation.")

    DATA.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="quantnex-web-update-", dir=str(DATA)) as temp_dir:
        temp = Path(temp_dir)
        archive, staged = temp / "source.zip", temp / "web"
        staged.mkdir()
        request = urllib.request.Request(archive_url, headers={"User-Agent": "QUANTNEX-Web-Updater"})
        download_bounded_archive(request, archive)

        count = 0
        total_size = 0
        with zipfile.ZipFile(archive) as source:
            for info in source.infolist():
                if info.is_dir():
                    continue
                parts = PurePosixPath(info.filename).parts
                try:
                    app_index = parts.index("apps")
                except ValueError:
                    continue
                if app_index + 1 >= len(parts) or parts[app_index + 1] != "web":
                    continue
                relative = _safe_web_relative(parts[app_index + 2:])
                if relative is None:
                    continue
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000 or "__pycache__" in relative.parts or relative.suffix == ".pyc":
                    continue
                if info.file_size > 20 * 1024 * 1024:
                    raise RuntimeError("The update contains an unexpectedly large file.")
                total_size += info.file_size
                count += 1
                if count > 1500 or total_size > 80 * 1024 * 1024:
                    raise RuntimeError("The update archive exceeds the safety limits.")
                target = staged.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read(info))

        if count == 0 or not (staged / "index.html").is_file() or not (staged / "app.js").is_file():
            raise RuntimeError("The pinned GitHub commit has no valid QUANTNEX Web workspace.")

        backup = DATA / "updates" / "backups" / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + sha[:7])
        installed_files: list[Path] = []
        try:
            for source_file in staged.rglob("*"):
                if not source_file.is_file():
                    continue
                relative = source_file.relative_to(staged)
                destination = _safe_web_destination(relative)
                if destination.is_file():
                    backup_file = backup / relative
                    backup_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, backup_file)
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(destination.name + ".quantnex-update-tmp")
                shutil.copy2(source_file, temporary)
                temporary.replace(destination)
                installed_files.append(relative)

            marker_tmp = VERSION_FILE.with_name(VERSION_FILE.name + ".tmp")
            marker_tmp.write_text(
                json.dumps({
                    "commit_sha": sha,
                    "version": "main@" + sha[:7],
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                }, indent=2),
                encoding="utf-8",
            )
            marker_tmp.replace(VERSION_FILE)
        except Exception:
            for relative in reversed(installed_files):
                destination = WEB / relative
                backup_file = backup / relative
                try:
                    if backup_file.is_file():
                        shutil.copy2(backup_file, destination)
                    elif destination.exists():
                        destination.unlink()
                except OSError:
                    pass
            raise


def install_worker(commit: dict) -> None:
    with LOCK:
        STATE.update(status="installing", message="Downloading and verifying the pinned GitHub source commit…")
    try:
        install_commit(commit)
        with LOCK:
            STATE.update(status="complete", message=f"QUANTNEX Web updated to main@{commit['sha'][:7]}. Refreshing the workspace…")
    except Exception as exc:
        print("[QUANTNEX updater]", exc, flush=True)
        with LOCK:
            STATE.update(status="error", message=str(exc))


def supervisor_managed() -> bool:
    return os.getenv("QUANTNEX_SUPERVISED", "").strip() == "1"


def ensure_supervisor_mode() -> None:
    """Route standalone server launches through the full API + source-update supervisor."""
    if supervisor_managed():
        return
    launcher = ROOT / "run_quantnex_services.py"
    if not launcher.is_file():
        raise RuntimeError("The QUANTNEX supervisor is missing. Restore run_quantnex_services.py and launch again.")
    print("[QUANTNEX] Starting the full workspace supervisor (Backend + Web + automatic source updates)…", flush=True)
    os.execv(sys.executable, [sys.executable, str(launcher)])


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def end_headers(self):
        if urlparse(self.path).path.endswith((".html", ".js", ".css")) or urlparse(self.path).path == "/":
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
        super().end_headers()

    def send_json(self, status: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/__quantnex/check":
            if supervisor_managed():
                try:
                    self.send_json(200, supervisor_update_status())
                except Exception as exc:
                    self.send_json(502, {"error": f"Supervisor update status failed: {exc}"})
                return
            try:
                latest = latest_commit()
                installed = installed_revision()
                update_available = bool(latest["sha"]) and latest["sha"] != installed
                details = update_summary(installed, latest) if update_available else {
                    "changes": [], "files_changed": 0, "commits_behind": 0
                }
                self.send_json(200, {
                    "installed": "main@" + installed[:7] if installed else "Unknown source revision",
                    "latest": "main@" + latest["sha"][:7],
                    "latest_message": latest["message"],
                    "update_available": update_available,
                    "release_notes": latest["html_url"],
                    "commit_sha": latest["sha"],
                    "published_at": latest.get("published_at"),
                    **details,
                })
            except Exception as exc:
                self.send_json(502, {"error": f"GitHub source check failed: {exc}"})
            return
        if path == "/__quantnex/status":
            with LOCK:
                state = dict(STATE)
            self.send_json(200, state)
            return
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        origin = self.headers.get("Origin")
        allowed_origins = {f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"}
        if origin not in allowed_origins:
            self.send_json(403, {"error": "Only the local QUANTNEX workspace can start an update."})
            return
        if path == "/__quantnex/check-now":
            if not supervisor_managed():
                self.send_json(409, {"error": "Immediate checks are available only when the QUANTNEX supervisor is running."})
                return
            try:
                queue_supervisor_check()
                self.send_json(202, {"status": "queued", "message": "An immediate source check was sent to the QUANTNEX supervisor."})
            except OSError as exc:
                self.send_json(500, {"error": f"Could not queue the update check: {exc}"})
            return
        if supervisor_managed():
            self.send_json(409, {"error": "Full source updates are handled by the QUANTNEX supervisor."})
            return
        if path != "/__quantnex/install":
            self.send_json(404, {"error": "Not found"})
            return
        try:
            commit = latest_commit()
            if commit["sha"] == installed_revision():
                self.send_json(409, {"error": "QUANTNEX is already at the latest GitHub commit."})
                return
            with LOCK:
                if STATE.get("status") == "installing":
                    self.send_json(409, {"error": "An update is already installing."})
                    return
                STATE.update(status="starting", message="Preparing the official GitHub update…")
            threading.Thread(target=install_worker, args=(commit,), daemon=True).start()
            self.send_json(202, {"status": "started", "version": "main@" + commit["sha"][:7]})
        except Exception as exc:
            self.send_json(502, {"error": str(exc)})


if __name__ == "__main__":
    ensure_supervisor_mode()
    print(f"QUANTNEX Web: http://{HOST}:{PORT}", flush=True)
    print("Keep this CMD window open while updates are installed.", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
