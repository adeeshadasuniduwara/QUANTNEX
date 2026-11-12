from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import urllib.request
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
REPO = "adeeshadasuniduwara/QUANTNEX"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
UPDATE_STATE = {"status": "idle", "message": "", "version": ""}
LOCK = threading.Lock()


def version_tuple(value):
    import re
    found = re.match(r"^v?(\\d+)\\.(\\d+)\\.(\\d+)", str(value or ""))
    return tuple(int(part) for part in found.groups()) if found else (0, 0, 0)


def current_version():
    try:
        return json.loads((ROOT / "version.json").read_text(encoding="utf-8")).get("version", "0.6.0")
    except Exception:
        return "0.6.0"


def github_json(url):
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "QUANTNEX-Local-Web-Updater"
    })
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def latest_release():
    return github_json(API)


def install_release(release):
    tag = release.get("tag_name") or release.get("name") or ""
    zip_url = release.get("zipball_url")
    if not tag or not zip_url:
        raise RuntimeError("GitHub did not return a valid published release ZIP.")

    with tempfile.TemporaryDirectory(prefix="quantnex-update-") as temp:
        temp_path = Path(temp)
        archive = temp_path / "release.zip"
        request = urllib.request.Request(zip_url, headers={"User-Agent": "QUANTNEX-Local-Web-Updater"})
        with urllib.request.urlopen(request, timeout=90) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)

        extract = temp_path / "source"
        extract.mkdir()
        with zipfile.ZipFile(archive) as zipped:
            for item in zipped.infolist():
                destination = (extract / item.filename).resolve()
                if not destination.is_relative_to(extract.resolve()):
                    raise RuntimeError("Release archive contains an unsafe path.")
            zipped.extractall(extract)

        candidates = list(extract.glob("*/apps/web"))
        if not candidates:
            raise RuntimeError("This release does not contain the QUANTNEX Web workspace.")
        source = candidates[0]
        files = [p for p in source.rglob("*") if p.is_file()]
        if not files:
            raise RuntimeError("The release Web workspace is empty.")

        # Keep the local launcher server alive; replace only the browser workspace assets.
        for src in files:
            relative = src.relative_to(source)
            destination = ROOT / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            staged = destination.with_name(destination.name + ".quantnex-new")
            shutil.copy2(src, staged)
            os.replace(staged, destination)

        version_file = ROOT / "version.json"
        staged_version = version_file.with_name("version.json.quantnex-new")
        staged_version.write_text(json.dumps({"version": tag, "release_name": release.get("name", tag)}, indent=2), encoding="utf-8")
        os.replace(staged_version, version_file)
    return tag


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        super().end_headers()

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/__quantnex/status":
            self.send_json(200, {"version": current_version(), **UPDATE_STATE})
            return
        if path == "/__quantnex/check":
            try:
                release = latest_release()
                latest = release.get("tag_name") or release.get("name") or "unknown"
                self.send_json(200, {
                    "installed": current_version(),
                    "latest": latest,
                    "update_available": version_tuple(latest) > version_tuple(current_version()),
                    "release_name": release.get("name") or latest,
                    "release_notes": release.get("html_url"),
                    "published_at": release.get("published_at"),
                })
            except Exception as exc:
                self.send_json(502, {"error": str(exc), "installed": current_version()})
            return
        super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/__quantnex/install":
            self.send_error(404)
            return
        with LOCK:
            if UPDATE_STATE["status"] == "installing":
                self.send_json(409, {"error": "An update is already installing."})
                return
            UPDATE_STATE.update(status="installing", message="Downloading and installing the published release…", version="")
        threading.Thread(target=self.run_install, daemon=True).start()
        self.send_json(202, {"status": "installing", "message": "Update started."})

    def run_install(self):
        try:
            release = latest_release()
            tag = install_release(release)
            UPDATE_STATE.update(status="complete", message=f"QUANTNEX Web updated to {tag}. Refreshing the workspace…", version=tag)
        except Exception as exc:
            UPDATE_STATE.update(status="error", message=str(exc), version="")

    def log_message(self, fmt, *args):
        print("[QUANTNEX Web] " + (fmt % args))


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 5500), Handler)
    print("QUANTNEX Web workspace: http://127.0.0.1:5500")
    print("Keep this window open while using the local updater.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nQUANTNEX Web server stopped.")
    finally:
        server.server_close()
