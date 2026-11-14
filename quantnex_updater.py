"""Safe, incremental QUANTNEX source updater for the local Web + Backend supervisor."""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

REPOSITORY = "adeeshadasuniduwara/QUANTNEX"
BRANCH = "main"
STATE_RELATIVE = Path("data") / "quantnex_update_state.json"
ROLLBACK_RELATIVE = Path("data") / "updates" / "last_update.json"
MAX_FILES = 300
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
              "dist", "build", "logs", "backups", "updates", "user_data", "secrets"}
SKIP_NAMES = {".env", ".env.local", ".env.production"}
SAFE_ROOTS = {".github", "apps", "backend", "docs", "shared", "services", "tests"}
SAFE_ROOT_FILES = {"README.md", "README_SI.md", "TODO.md", "FEATURE_STATUS_SI.md",
                   "requirements.txt", "pyproject.toml", "quantnex_updater.py",
                   "run_quantnex.bat", "run_quantnex_services.py", "run_backend.bat"}


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
    # Git paths use POSIX separators, but Path() is Windows-native on the
    # target platform. Reject Windows separators, drive/ADS syntax and NULs
    # before converting to Path so a crafted filename cannot escape the root.
    if not isinstance(raw, str) or not raw or any(char in raw for char in ("\\", ":", "\x00")):
        return None
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


def _safe_destination(root: Path, relative: Path) -> Path:
    """Resolve an update target and refuse symlink/path traversal outside root."""
    base = root.resolve()
    try:
        destination = (base / relative).resolve()
        destination.relative_to(base)
    except (OSError, RuntimeError, ValueError) as exc:
        raise UpdateError("An update destination resolves outside the QUANTNEX workspace.") from exc
    if destination == base:
        raise UpdateError("An update destination cannot replace the QUANTNEX workspace root.")
    return destination


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


def _bootstrap_snapshot(root: Path, latest_sha: str) -> dict:
    """One-time safe source bootstrap for ZIP installs without Git metadata."""
    url = f"https://codeload.github.com/{REPOSITORY}/zip/{latest_sha}"
    request = urllib.request.Request(url, headers={"User-Agent": "QUANTNEX-Automatic-Updater"})
    with urllib.request.urlopen(request, timeout=120) as response:
        archive_bytes = response.read(150 * 1024 * 1024 + 1)
    if len(archive_bytes) > 150 * 1024 * 1024:
        raise UpdateError("The one-time source bootstrap exceeds the 150 MB download safety limit.")

    staged_root = root / "data" / "updates" / "bootstrap-staging"
    if staged_root.exists():
        shutil.rmtree(staged_root)
    staged_root.mkdir(parents=True, exist_ok=True)
    count = 0
    total = 0
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            parts = PurePosixPath(info.filename).parts
            if len(parts) < 2:
                continue
            relative = _safe_relative("/".join(parts[1:]))
            if relative is None:
                continue
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                continue
            if info.file_size > MAX_FILE_BYTES:
                raise UpdateError("The bootstrap contains a source file above the 20 MB safety limit.")
            count += 1
            total += info.file_size
            if count > 1500 or total > MAX_TOTAL_BYTES:
                raise UpdateError("The one-time source bootstrap exceeds the extracted-file safety limits.")
            target = staged_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
    if count == 0 or not (staged_root / "run_quantnex_services.py").is_file():
        raise UpdateError("The official GitHub archive did not contain a valid QUANTNEX source workspace.")

    backup_root = root / "data" / "updates" / "backups" / (
        datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-initial-bootstrap")
    touched = []
    try:
        for source in staged_root.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(staged_root)
            destination = _safe_destination(root, relative)
            if destination.is_file():
                backup = backup_root / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup)
            touched.append(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + ".quantnex-update-tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
        _save_state(root, latest_sha)
    except Exception:
        for relative in reversed(touched):
            destination, backup = _safe_destination(root, relative), backup_root / relative
            try:
                if backup.is_file():
                    shutil.copy2(backup, destination)
                elif destination.exists():
                    destination.unlink()
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(staged_root, ignore_errors=True)
    changed = [str(path).replace("\\", "/") for path in touched]
    return {"status": "updated", "version": "main@" + latest_sha[:7],
            "changed_files": changed,
            "restart_required": True,
            "message": f"Installed the initial official source snapshot ({count} files)."}



def _write_rollback_manifest(root: Path, previous_sha: str, installed_sha: str,
                             backup_root: Path, touched: list[Path]) -> None:
    """Persist the exact pre-update file set so a failed startup can be rolled back."""
    entries = []
    seen = set()
    for relative in touched:
        key = relative.as_posix()
        if key in seen:
            continue
        seen.add(key)
        entries.append({"path": key, "existed_before": (backup_root / relative).is_file()})
    manifest = {
        "previous_sha": previous_sha,
        "installed_sha": installed_sha,
        "backup_dir": backup_root.relative_to(root).as_posix(),
        "entries": entries,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path = root / ROLLBACK_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def rollback_last_update(root: Path) -> bool:
    """Restore the previous source snapshot after the new version fails health checks."""
    root = root.resolve()
    manifest_path = root / ROLLBACK_RELATIVE
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        current = _load_state(root).get("commit_sha")
        previous_sha = manifest.get("previous_sha")
        installed_sha = manifest.get("installed_sha")
        if current != installed_sha or not _valid_sha(previous_sha) or not _valid_sha(installed_sha):
            return False
        backup_rel = PurePosixPath(manifest.get("backup_dir", ""))
        if backup_rel.is_absolute() or any(part in ("", ".", "..") for part in backup_rel.parts):
            return False
        backup_root = (root / Path(*backup_rel.parts)).resolve()
        backup_root.relative_to(root)
        entries = manifest.get("entries")
        if not isinstance(entries, list) or not entries:
            return False
        plan = []
        for item in entries:
            relative = _safe_relative(item.get("path"))
            if relative is None or not isinstance(item.get("existed_before"), bool):
                return False
            destination = _safe_destination(root, relative)
            backup = (backup_root / relative).resolve()
            backup.relative_to(backup_root)
            if item["existed_before"] and not backup.is_file():
                return False
            plan.append((destination, backup, item["existed_before"]))
        for destination, backup, existed_before in reversed(plan):
            if existed_before:
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(destination.name + ".quantnex-rollback-tmp")
                shutil.copy2(backup, temporary)
                os.replace(temporary, destination)
            elif destination.exists():
                destination.unlink()
        _save_state(root, previous_sha)
        manifest_path.unlink(missing_ok=True)
        return True
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return False


def confirm_update(root: Path) -> bool:
    """Discard the one-shot rollback marker after both local services pass startup checks."""
    root = root.resolve()
    path = root / ROLLBACK_RELATIVE
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if _load_state(root).get("commit_sha") != manifest.get("installed_sha"):
            return False
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except (OSError, ValueError, TypeError):
        return False


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
        return _bootstrap_snapshot(root, latest_sha)
    if installed_sha == latest_sha:
        return {"status": "current", "version": "main@" + latest_sha[:7],
                "changed_files": [], "restart_required": False}

    comparison = _request_json(
        f"https://api.github.com/repos/{REPOSITORY}/compare/{installed_sha}...{latest_sha}"
    )
    if comparison.get("status") not in ("ahead", "identical") or comparison.get("too_large"):
        raise UpdateError("The update history is not a safe incremental patch; existing files were left unchanged.")
    changes = comparison.get("files") or []
    if len(changes) >= MAX_FILES:
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
                destination = _safe_destination(root, rel)
                backup = backup_root / rel
                if destination.is_file():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, backup)
                touched.append(rel)
            if status == "removed":
                destination = _safe_destination(root, relative)
                if destination.exists():
                    destination.unlink()
            else:
                source, destination = staged_root / relative, _safe_destination(root, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(destination.name + ".quantnex-update-tmp")
                shutil.copy2(source, temporary)
                os.replace(temporary, destination)
                if status == "renamed" and previous_relative and previous_relative != relative:
                    old = _safe_destination(root, previous_relative)
                    if old.exists():
                        old.unlink()
        _write_rollback_manifest(root, installed_sha, latest_sha, backup_root, touched)
        _save_state(root, latest_sha)
    except Exception:
        for rel in reversed(touched):
            destination, backup = _safe_destination(root, rel), backup_root / rel
            try:
                if backup.is_file():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, destination)
                elif destination.exists():
                    destination.unlink()
            except OSError:
                pass
        (root / ROLLBACK_RELATIVE).unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staged_root, ignore_errors=True)

    changed = [str(item[1]).replace("\\", "/") for item in planned]
    restart_required = any(path.endswith((".py", ".js", ".html", ".css", ".json", ".toml", ".txt", ".bat"))
                           for path in changed)
    return {"status": "updated", "version": "main@" + latest_sha[:7],
            "changed_files": changed, "restart_required": restart_required,
            "message": f"Applied {len(changed)} changed source files."}
