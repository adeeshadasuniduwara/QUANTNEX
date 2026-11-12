"""Loopback Web server and GitHub Release updater for QUANTNEX."""
from __future__ import annotations
import json, re, shutil, tempfile, threading, urllib.request, urllib.error, zipfile
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent.parent
DATA = ROOT / "data"
VERSION_FILE = DATA / "quantnex_web_version.json"
REPO = "adeeshadasuniduwara/QUANTNEX"
HOST, PORT = "127.0.0.1", 5500
FALLBACK_VERSION = "0.6.0"
LOCK = threading.Lock()
STATE = {"status": "idle", "message": ""}

def version_tuple(value):
    parts = re.findall(r"\d+", str(value))
    return tuple(map(int, parts)) if parts else (0,)

def installed_version():
    try:
        return str(json.loads(VERSION_FILE.read_text(encoding="utf-8")).get("version") or FALLBACK_VERSION)
    except (OSError, ValueError, AttributeError):
        return FALLBACK_VERSION

def github_json(url):
    req = urllib.request.Request(url, headers={"Accept":"application/vnd.github+json","User-Agent":"QUANTNEX-Web-Updater","X-GitHub-Api-Version":"2022-11-28"})
    with urllib.request.urlopen(req, timeout=25) as res:
        return json.loads(res.read().decode("utf-8"))

def latest_release():
    return github_json(f"https://api.github.com/repos/{REPO}/releases/latest")

def install_release(release):
    tag = str(release.get("tag_name") or "").strip()
    zip_url = str(release.get("zipball_url") or "").strip()
    if not tag or not zip_url:
        raise RuntimeError("The GitHub release does not include a source ZIP.")
    DATA.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="quantnex-web-update-", dir=str(DATA)) as tmp:
        tmp = Path(tmp)
        archive, staged = tmp / "release.zip", tmp / "web"
        staged.mkdir()
        req = urllib.request.Request(zip_url, headers={"User-Agent":"QUANTNEX-Web-Updater"})
        with urllib.request.urlopen(req, timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        count = 0
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                parts = PurePosixPath(info.filename).parts
                try:
                    idx = parts.index("apps")
                except ValueError:
                    continue
                if idx + 1 >= len(parts) or parts[idx + 1] != "web":
                    continue
                relative = PurePosixPath(*parts[idx + 2:])
                if not relative.parts or any(p in ("", ".", "..") for p in relative.parts):
                    continue
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000 or "__pycache__" in relative.parts or relative.suffix == ".pyc":
                    continue
                target = staged.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(info))
                count += 1
        if count == 0 or not (staged / "index.html").is_file():
            raise RuntimeError("The release ZIP has no valid apps/web workspace.")
        backup = DATA / "updates" / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
        for src in staged.rglob("*"):
            if src.is_file():
                rel = src.relative_to(staged)
                current = WEB / rel
                if current.is_file():
                    dest = backup / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(current, dest)
        # Replace only release-provided Web files. Keep unrelated files and all user data.
        for src in staged.rglob("*"):
            if src.is_file():
                rel = src.relative_to(staged)
                dest = WEB / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
    VERSION_FILE.write_text(json.dumps({"version":tag.lstrip("v"),"tag":tag,"installed_at":datetime.now(timezone.utc).isoformat()},indent=2),encoding="utf-8")

def install_worker(release):
    with LOCK:
        STATE.update(status="installing", message="Downloading and installing the official release…")
    try:
        install_release(release)
        with LOCK:
            STATE.update(status="complete", message=f"QUANTNEX Web {release.get('tag_name')} installed. Refreshing this browser…")
    except Exception as exc:
        print("[QUANTNEX updater]", exc, flush=True)
        with LOCK:
            STATE.update(status="error", message=str(exc))

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)
    def end_headers(self):
        if urlparse(self.path).path.endswith((".html",".js",".css")) or urlparse(self.path).path == "/":
            self.send_header("Cache-Control","no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma","no-cache")
        super().end_headers()
    def send_json(self, status, data):
        body=json.dumps(data).encode()
        self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        path=urlparse(self.path).path
        if path == "/__quantnex/check":
            try:
                release=latest_release(); installed=installed_version(); latest=str(release.get("tag_name") or "")
                self.send_json(200,{"installed": "v"+installed.lstrip("v"),"latest":latest,
                    "update_available":bool(latest) and version_tuple(latest)>version_tuple(installed),
                    "release_notes":release.get("html_url"),"zipball_url":release.get("zipball_url")})
            except Exception as exc:
                self.send_json(502,{"error":f"GitHub Release check failed: {exc}"})
            return
        if path == "/__quantnex/status":
            with LOCK: state=dict(STATE)
            self.send_json(200,state); return
        super().do_GET()
    def do_POST(self):
        if urlparse(self.path).path != "/__quantnex/install":
            self.send_json(404,{"error":"Not found"}); return
        origin=self.headers.get("Origin")
        if origin and urlparse(origin).netloc not in (f"{HOST}:{PORT}",f"localhost:{PORT}"):
            self.send_json(403,{"error":"Request origin is not allowed."}); return
        try:
            release=latest_release(); tag=str(release.get("tag_name") or "")
            if not tag or version_tuple(tag)<=version_tuple(installed_version()):
                self.send_json(409,{"error":"No newer published release is available."}); return
            with LOCK:
                if STATE.get("status")=="installing":
                    self.send_json(409,{"error":"An update is already installing."}); return
                STATE.update(status="starting",message="Preparing the official release…")
            threading.Thread(target=install_worker,args=(release,),daemon=True).start()
            self.send_json(202,{"status":"started","version":tag})
        except Exception as exc:
            self.send_json(502,{"error":str(exc)})

if __name__ == "__main__":
    print(f"QUANTNEX Web: http://{HOST}:{PORT}",flush=True)
    print("Keep this CMD window open while installing updates.",flush=True)
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
