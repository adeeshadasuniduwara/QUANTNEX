"""Safe, incremental QUANTNEX source updater for the Windows supervisor."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

REPOSITORY = "adeeshadasuniduwara/QUANTNEX"
BRANCH = "main"
STATE_RELATIVE = Path("data") / "quantnex_update_state.json"
MAX_FILES = 300
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
              "dist", "build", "logs", "backups", "updates", "user_data", "secrets"}
SKIP_NAMES = {".env", ".env.local", ".env.production"}
SAFE_ROOTS = {".github", "apps", "backend", "docs", "shared", "services", "tests"}
SAFE_ROOT_FILES = {"README.md", "README_SI.md", "TODO.md", "FEATURE_STATUS_SI.md",
                   "requirements.txt", "pyproject.toml", "run_quantnex.bat",
                   "run_quantnex_services.py", "run_backend.bat"}


class UpdateError(RuntimeError):
    pass


def _request_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "QUANTNEX-Automatic-Updater",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise UpdateError("GitHub returned an invalid response.")
    return result


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def _safe_relative(raw: str) -> Path | None:
    posix = PurePosixPath(raw)
    parts = posix.parts
    if not parts or posix.is_absolute() or any(part in ("", ".", "..") for part in parts):
        return None
    if parts[0] not in SAFE_ROOTS and raw not in SAFE_ROOT_FILES:
        return None
    if any(part in SKIP_PARTS for part in parts) or any(part.lower() in SKIP_NAMES for part in parts):
        return None
    lower = raw.lower()
    if lower.endswith((".sqlite", ".sqlite3", ".db", ".pyc", ".pyo")):
        return None
    if any(token in lower for token in ("credential", "private_key", "wallet_backup")):
        return None
    return Path(*parts)


def _load_state(root: Path) -> dict:
    try:
        state = json.loads((root / STATE_RELATIVE).read_text(encoding="utf-8"))
        if _valid_sha(state.get("commit_sha")):
            return state
    except (OSError, ValueError, AttributeError):
        pass
    # The Web updater marker is deliberately not reused: historically it tracked
    # only Web files, not the full application source revision.
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
            text=True, timeout=5, check=True,
        )
        revision = result.stdout.strip().lower()
        if _valid_sha(revision):
            return {"commit_sha": revision}
    except (OSError, subprocess.SubprocessError):
        pass
    return {}


def _save_state(root: Path, sha: str) -> None:
    path = root / STATE_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "commit_sha": sha,
        "version": "main@" + sha[:7],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def check_and_apply(root: Path) -> dict:
    """Apply verified changed source files; caller restarts child services if required."""
    root = root.resolve()
    latest = _request_json(f"https://api.github.com/repos/{REPOSITORY}/commits/{BRANCH}")
    latest_sha = latest.get("sha")
    if not _valid_sha(latest_sha):
        raise UpdateError("GitHub did not provide a valid commit SHA.")

    state = _load_state(root)
    installed_sha = state.get("commit_sha")
    if not _valid_sha(installed_sha):
        _save_state(root, latest_sha)
        return {"status": "baseline", "version": "main@" + latest_sha[:7],
                "changed_files": [], "restart_required": False}
    if installed_sha == latest_sha:
        return {"status": "current", "version": "main@" + latest_sha[:7],
                "changed_files": [], "restart_required": False}

    comparison = _request_json(
        f"https://api.github.com/repos/{REPOSITORY}/compare/{installed_sha}...{latest_sha}"
    )
    if comparison.get("status") not in ("ahead", "identical") or comparison.get("too_large"):
        raise UpdateError("The update history is not a safe incremental patch; existing files were left unchanged.")
    changes = comparison.get("files") or []
    if len(changes) > MAX_FILES:
        raise UpdateError("The update exceeds the incremental file-count safety limit.")

    planned = []
    total_size = 0
    for item in changes:
        status, raw_path = item.get("status"), item.get("filename", "")
        relative = _safe_relative(raw_path)
        if relative is None:
            continue
        previous = item.get("previous_filename")
        previous_relative = _safe_relative(previous) if previous else None
        if status == "renamed" and previous_relative is None:
            raise UpdateError("A renamed file failed path validation.")
        payload = None
        if status != "removed":
            url = f"https://raw.githubusercontent.com/{REPOSITORY}/{latest_sha}/{raw_path}"
            request = urllib.request.Request(url, headers={"User-Agent": "QUANTNEX-Automatic-Updater"})
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = response.read(MAX_FILE_BYTES + 1)
            if len(payload) > MAX_FILE_BYTES:
                raise UpdateError("An update file exceeds the 20 MB safety limit.")
            total_size += len(payload)
            if total_size > MAX_TOTAL_BYTES:
                raise UpdateError("The update exceeds the 100 MB safety limit.")
        planned.append((status, relative, previous_relative, payload))

    if not planned:
        _save_state(root, latest_sha)
        return {"status": "current", "version": "main@" + latest_sha[:7],
                "changed_files": [], "restart_required": False}

    backup_root = root / "data" / "updates" / "backups" / (
        datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + installed_sha[:7])
    staged_root = root / "data" / "updates" / "staging" / latest_sha[:12]
    if staged_root.exists():
        shutil.rmtree(staged_root)
    staged_root.mkdir(parents=True, exist_ok=True)
    for status, relative, _, payload in planned:
        if payload is not None:
            target = staged_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)

    touched = []
    try:
        for status, relative, previous_relative, payload in planned:
            targets = [relative]
            if status == "renamed" and previous_relative and previous_relative != relative:
                targets.append(previous_relative)
            for rel in targets:
                destination = root / rel
                backup = backup_root / rel
                if destination.is_file():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, backup)
                touched.append(rel)
            if status == "removed":
                destination = root / relative
                if destination.exists():
                    destination.unlink()
            else:
                source, destination = staged_root / relative, root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(destination.name + ".quantnex-update-tmp")
                shutil.copy2(source, temporary)
                os.replace(temporary, destination)
                if status == "renamed" and previous_relative and previous_relative != relative:
                    old = root / previous_relative
                    if old.exists():
                        old.unlink()
        _save_state(root, latest_sha)
    except Exception:
        for rel in reversed(touched):
            destination, backup = root / rel, backup_root / rel
            try:
                if backup.is_file():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, destination)
                elif destination.exists():
                    destination.unlink()
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(staged_root, ignore_errors=True)

    changed = [str(item[1]).replace("\\", "/") for item in planned]
    restart_required = any(path.endswith((".py", ".js", ".html", ".css", ".json", ".toml", ".txt", ".bat"))
                           for path in changed)
    return {"status": "updated", "version": "main@" + latest_sha[:7],
            "changed_files": changed, "restart_required": restart_required,
            "message": f"Applied {len(changed)} changed source files."}
