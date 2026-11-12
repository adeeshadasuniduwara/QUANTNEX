"""Loopback-only Web server with a pinned-commit GitHub source updater."""
from __future__ import annotations

import json
import re
import shutil
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
REPO = "adeeshadasuniduwara/QUANTNEX"
BRANCH = "main"
HOST, PORT = "127.0.0.1", 5500
LOCK = threading.Lock()
STATE = {"status": "idle", "message": ""}


def installed_revision() -> str:
    try:
        value = json.loads(VERSION_FILE.read_text(encoding="utf-8")).get("commit_sha", "")
        return value if re.fullmatch(r"[0-9a-f]{40}", str(value)) else ""
    except (OSError, ValueError, AttributeError):
        return ""


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
        with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)

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
                relative = PurePosixPath(*parts[app_index + 2:])
                if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
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
                destination = WEB / relative
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
            try:
                latest = latest_commit()
                installed = installed_revision()
                self.send_json(200, {
                    "installed": "main@" + installed[:7] if installed else "Unknown source revision",
                    "latest": "main@" + latest["sha"][:7],
                    "latest_message": latest["message"],
                    "update_available": bool(latest["sha"]) and latest["sha"] != installed,
                    "release_notes": latest["html_url"],
                    "commit_sha": latest["sha"],
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
        if urlparse(self.path).path != "/__quantnex/install":
            self.send_json(404, {"error": "Not found"})
            return
        origin = self.headers.get("Origin")
        allowed_origins = {f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"}
        if origin not in allowed_origins:
            self.send_json(403, {"error": "Only the local QUANTNEX workspace can start an update."})
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
    print(f"QUANTNEX Web: http://{HOST}:{PORT}", flush=True)
    print("Keep this CMD window open while updates are installed.", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
