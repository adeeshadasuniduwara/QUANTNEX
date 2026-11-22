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
import xml.etree.ElementTree as ET
import time
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
              "dist", "build", "logs", "backups", "updates", "user_data", "user-data", "secrets", "data", "storage", "uploads", "instance", "runtime", "profiles"}
SKIP_NAMES = {".env", ".env.local", ".env.production"}
SAFE_ROOTS = {".github", "apps", "backend", "docs", "scripts", "shared", "services", "tests"}
SAFE_ROOT_FILES = {"README.md", "README_SI.md", "TODO.md", "FEATURE_STATUS_SI.md",
                   "requirements.txt", "pyproject.toml", "quantnex_updater.py",
                   "run_quantnex.bat", "run_quantnex_services.py", "run_backend.bat", ".gitignore"}


class UpdateError(RuntimeError):
    pass


def _request_latest_commit_sha() -> str:
    """Resolve only the current main tip through GitHub's Atom feed (not the rate-limited REST API)."""
    url = f"https://github.com/{REPOSITORY}/commits/{BRANCH}.atom"
    request = urllib.request.Request(url, headers={
        "Accept": "application/atom+xml, application/xml, text/xml",
        "User-Agent": "QUANTNEX-Automatic-Updater",
        "Cache-Control": "no-cache",
    })
    payload = None
    last_error = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read(2 * 1024 * 1024 + 1)
            break
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in (403, 429, 500, 502, 503, 504) or attempt == 3:
                raise UpdateError(f"GitHub update check temporarily unavailable (HTTP {exc.code}). Existing QUANTNEX remains active.") from exc
            retry_after = exc.headers.get("Retry-After", "")
            try:
                delay = min(900, max(1, int(retry_after)))
            except (TypeError, ValueError):
                delay = min(900, 30 * (2 ** attempt))
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == 3:
                raise UpdateError("GitHub update check network failure; retry on the next scheduled check.") from exc
            time.sleep(min(300, 15 * (2 ** attempt)))
    if payload is None:
        raise UpdateError("GitHub update check failed; installed source remains unchanged.") from last_error
    if len(payload) > 2 * 1024 * 1024:
        raise UpdateError("GitHub returned an unexpectedly large commit feed.")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise UpdateError("GitHub returned an invalid main-branch commit feed.") from exc
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "id":
            match = re.search(r"/([0-9a-f]{40})$", (element.text or "").strip())
            if match:
                return match.group(1)
    raise UpdateError("GitHub's main-branch feed did not contain a valid commit SHA.")


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
    if any(part.lower() in SKIP_PARTS for part in parts) or any(part.lower() in SKIP_NAMES for part in parts):
        return None
    if any(part.lower() == ".env" or part.lower().startswith(".env.") for part in parts):
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


def _save_state(root: Path, sha: str, previous_commit_sha: str | None = None) -> None:
    path = root / STATE_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "commit_sha": sha,
        "version": "main@" + sha[:7],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if _valid_sha(previous_commit_sha):
        state["previous_commit_sha"] = previous_commit_sha
        state["compare_url"] = f"https://github.com/{REPOSITORY}/compare/{previous_commit_sha}...{sha}"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
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
        _save_managed_paths(
            root, latest_sha,
            [path.relative_to(staged_root).as_posix()
             for path in staged_root.rglob("*") if path.is_file()],
        )
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
        previous_manifest = manifest.get("previous_managed_manifest")
        managed_manifest_path = root / MANAGED_RELATIVE
        if isinstance(previous_manifest, str):
            managed_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            managed_manifest_path.write_text(previous_manifest, encoding="utf-8")
        elif previous_manifest is None:
            managed_manifest_path.unlink(missing_ok=True)
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


MANAGED_RELATIVE = Path("data") / "updates" / "managed_source_files.json"
MAX_SNAPSHOT_FILES = 1500
MAX_SNAPSHOT_BYTES = 100 * 1024 * 1024


def _managed_paths_from_archive(commit_sha: str) -> list[str]:
    """Read the full safe source-file list from the pinned archive without REST API calls."""
    url = f"https://codeload.github.com/{REPOSITORY}/zip/{commit_sha}"
    request = urllib.request.Request(url, headers={"User-Agent": "QUANTNEX-Automatic-Updater"})
    with urllib.request.urlopen(request, timeout=120) as response:
        archive_bytes = response.read(300 * 1024 * 1024 + 1)
    if len(archive_bytes) > 300 * 1024 * 1024:
        raise UpdateError("The source archive exceeds the 300 MB download safety limit.")
    paths = set()
    try:
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
                if mode != 0o120000:
                    paths.add(relative.as_posix())
    except zipfile.BadZipFile as exc:
        raise UpdateError("GitHub returned an invalid source archive.") from exc
    if len(paths) > MAX_SNAPSHOT_FILES:
        raise UpdateError("The source snapshot exceeds the 1,500-file safety limit.")
    if "run_quantnex_services.py" not in paths:
        raise UpdateError("The pinned archive is not a valid QUANTNEX source workspace.")
    return sorted(paths)


def _load_managed_paths(root: Path, fallback_sha: str) -> list[str]:
    path = root / MANAGED_RELATIVE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        paths = payload.get("paths")
        if isinstance(paths, list) and all(
            isinstance(item, str) and _safe_relative(item) is not None for item in paths
        ):
            return sorted(set(paths))
    except (OSError, ValueError, AttributeError):
        pass
    # Older installations did not record a managed-file manifest. Reconstruct
    # the previous exact source set from its pinned archive before syncing the new one.
    return _managed_paths_from_archive(fallback_sha)


def _save_managed_paths(root: Path, commit_sha: str, paths: list[str]) -> None:
    path = root / MANAGED_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "commit_sha": commit_sha,
        "paths": sorted(set(paths)),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _stage_full_snapshot(root: Path, commit_sha: str, expected_paths: list[str]) -> Path:
    """Download and validate one complete pinned GitHub ZIP before touching installed files."""
    url = f"https://codeload.github.com/{REPOSITORY}/zip/{commit_sha}"
    request = urllib.request.Request(url, headers={"User-Agent": "QUANTNEX-Automatic-Updater"})
    with urllib.request.urlopen(request, timeout=180) as response:
        archive_bytes = response.read(300 * 1024 * 1024 + 1)
    if len(archive_bytes) > 300 * 1024 * 1024:
        raise UpdateError("The complete source archive exceeds the 300 MB download safety limit.")

    staged_root = root / "data" / "updates" / "staging" / (commit_sha[:12] + "-full")
    if staged_root.exists():
        shutil.rmtree(staged_root)
    staged_root.mkdir(parents=True, exist_ok=True)
    expected = set(expected_paths)
    extracted: set[str] = set()
    total = 0
    try:
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
                key = relative.as_posix()
                if key not in expected:
                    continue
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    continue
                if info.file_size > MAX_FILE_BYTES:
                    raise UpdateError(f"Source file exceeds the 20 MB limit: {key}")
                total += info.file_size
                if total > MAX_SNAPSHOT_BYTES:
                    raise UpdateError("The complete source snapshot exceeds the 100 MB extracted-size limit.")
                target = staged_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))
                extracted.add(key)
        missing = expected - extracted
        if missing:
            sample = ", ".join(sorted(missing)[:8])
            raise UpdateError("The GitHub archive is incomplete; missing tracked files: " + sample)
        if "run_quantnex_services.py" not in extracted:
            raise UpdateError("The GitHub archive is not a valid QUANTNEX source workspace.")
        return staged_root
    except Exception:
        shutil.rmtree(staged_root, ignore_errors=True)
        raise


def check_and_apply(root: Path, force_reconcile: bool = False, _latest_retry: int = 0) -> dict:
    """Install only the newest main snapshot; intermediate commits are never queued."""
    root = root.resolve()
    latest_sha = _request_latest_commit_sha()
    if not _valid_sha(latest_sha):
        raise UpdateError("GitHub did not provide a valid commit SHA.")

    state = _load_state(root)
    installed_sha = state.get("commit_sha")
    if not _valid_sha(installed_sha):
        return _bootstrap_snapshot(root, latest_sha)
    if installed_sha == latest_sha and not force_reconcile:
        return {"status": "current", "version": "main@" + latest_sha[:7],
                "changed_files": [], "restart_required": False}

    # Resolve the complete tracked source set for both revisions. This avoids
    # GitHub Compare API's 300-file response ceiling and catches stale/deleted files.
    previous_paths = _load_managed_paths(root, installed_sha)
    latest_paths = _managed_paths_from_archive(latest_sha)
    staged_root = _stage_full_snapshot(root, latest_sha, latest_paths)
    # main can advance while a large ZIP is downloading. Discard that staged
    # revision and resolve again before touching the installed workspace.
    confirmed_latest_sha = _request_latest_commit_sha()
    if confirmed_latest_sha != latest_sha:
        shutil.rmtree(staged_root, ignore_errors=True)
        if _latest_retry >= 4:
            raise UpdateError("main kept changing during update download; the installer will retry on the next check.")
        print(f"[AUTO UPDATE] A newer main revision appeared during download ({latest_sha[:7]} -> {confirmed_latest_sha[:7]}). Skipping the older snapshot.", flush=True)
        return check_and_apply(root, force_reconcile=force_reconcile, _latest_retry=_latest_retry + 1)
    latest_set = set(latest_paths)
    removed_paths = sorted(set(previous_paths) - latest_set)
    changed_paths = []
    total_changed = 0
    for key in latest_paths:
        source = staged_root / Path(*PurePosixPath(key).parts)
        destination = _safe_destination(root, Path(*PurePosixPath(key).parts))
        if not destination.is_file() or destination.read_bytes() != source.read_bytes():
            changed_paths.append(key)
            total_changed += source.stat().st_size
    planned_paths = sorted(set(changed_paths) | set(removed_paths))
    if not planned_paths:
        _save_managed_paths(root, latest_sha, latest_paths)
        _save_state(root, latest_sha)
        shutil.rmtree(staged_root, ignore_errors=True)
        return {"status": "current", "version": "main@" + latest_sha[:7],
                "changed_files": [], "restart_required": False}

    backup_root = root / "data" / "updates" / "backups" / (
        datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + installed_sha[:7])
    touched: list[Path] = []
    old_manifest_path = root / MANAGED_RELATIVE
    old_manifest_bytes = old_manifest_path.read_bytes() if old_manifest_path.is_file() else None
    try:
        # Stage/verify every remote file before this point. Now back up all
        # affected local source files, then atomically replace or remove them.
        for key in planned_paths:
            relative = Path(*PurePosixPath(key).parts)
            destination = _safe_destination(root, relative)
            if destination.is_file():
                backup = backup_root / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup)
            touched.append(relative)

        for key in changed_paths:
            relative = Path(*PurePosixPath(key).parts)
            source = staged_root / relative
            destination = _safe_destination(root, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + ".quantnex-update-tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)

        for key in removed_paths:
            destination = _safe_destination(root, Path(*PurePosixPath(key).parts))
            if destination.exists():
                destination.unlink()

        _write_rollback_manifest(root, installed_sha, latest_sha, backup_root, touched)
        rollback_path = root / ROLLBACK_RELATIVE
        rollback_data = json.loads(rollback_path.read_text(encoding="utf-8"))
        rollback_data["previous_managed_paths"] = previous_paths
        rollback_data["previous_managed_manifest"] = (
            old_manifest_bytes.decode("utf-8") if old_manifest_bytes is not None else None
        )
        temporary_rollback = rollback_path.with_suffix(".tmp")
        temporary_rollback.write_text(json.dumps(rollback_data, indent=2), encoding="utf-8")
        os.replace(temporary_rollback, rollback_path)
        _save_managed_paths(root, latest_sha, latest_paths)
        _save_state(root, latest_sha, previous_commit_sha=installed_sha)
    except Exception:
        for relative in reversed(touched):
            destination = _safe_destination(root, relative)
            backup = backup_root / relative
            try:
                if backup.is_file():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, destination)
                elif destination.exists():
                    destination.unlink()
            except OSError:
                pass
        if old_manifest_bytes is not None:
            old_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            old_manifest_path.write_bytes(old_manifest_bytes)
        else:
            old_manifest_path.unlink(missing_ok=True)
        (root / ROLLBACK_RELATIVE).unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staged_root, ignore_errors=True)

    changed = [*changed_paths, *removed_paths]
    restart_required = any(path.endswith((".py", ".js", ".html", ".css", ".json", ".toml", ".txt", ".bat"))
                           for path in changed)
    return {"status": "updated", "version": "main@" + latest_sha[:7],
            "changed_files": changed, "restart_required": restart_required,
            "message": f"Fully synchronized {len(changed_paths)} updated/added and {len(removed_paths)} removed source files."}
