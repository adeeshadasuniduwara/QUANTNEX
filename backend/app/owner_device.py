"""Provision a Windows-user and machine-bound QUANTNEX Owner Device identity.

The private Ed25519 key is protected with Windows DPAPI (current-user scope)
and never written in plaintext. The signed device claim is non-secret. The
public key is intentionally pinned in source only after the owner's device
has been provisioned and its public key reviewed.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PRODUCT = "QUANTNEX"
CLAIM_SCHEMA = 1
PRIVATE_KEY_MAGIC = b"QNX-OWNER-DPAPI-V1:"
DPAPI_ENTROPY = b"QUANTNEX_OWNER_DEVICE_PRIVATE_KEY_V1"
# Set this to the owner's public key only after the owner laptop has completed
# the one-time provisioning step. Empty means owner verification fails closed.
PINNED_OWNER_PUBLIC_KEY_B64 = ""


def default_identity_directory() -> Path:
    """Keep owner identity outside the repository and its update/backup folders."""
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if not local_app_data:
        raise RuntimeError("Windows LOCALAPPDATA is unavailable; cannot store the Owner Device identity safely.")
    return Path(local_app_data) / PRODUCT / "Owner"


def _machine_fingerprint() -> str:
    """Return a stable, non-secret Windows MachineGuid fingerprint."""
    if sys.platform != "win32":
        raise RuntimeError("Owner Device provisioning currently requires Windows.")
    import winreg

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\\Microsoft\\Cryptography") as key:
        machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
    normalized = str(machine_guid).strip().lower()
    if not normalized:
        raise RuntimeError("Windows did not provide a usable MachineGuid.")
    return hashlib.sha256((PRODUCT + ":OWNER-DEVICE:V1:" + normalized).encode("utf-8")).hexdigest()


class _DataBlob(ctypes.Structure):
    # DATA_BLOB is a DWORD byte count followed by a pointer to its bytes.
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _as_blob(value: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(value)
    blob = _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _dpapi_transform(value: bytes, *, protect: bool) -> bytes:
    """Use CryptProtectData/CryptUnprotectData with current-user DPAPI scope."""
    if sys.platform != "win32":
        raise RuntimeError("Windows DPAPI is required to protect the Owner Device private key.")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    input_blob, input_buffer = _as_blob(value)
    entropy_blob, entropy_buffer = _as_blob(DPAPI_ENTROPY)
    output_blob = _DataBlob()
    flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN; do not show unexpected UI.
    if protect:
        function = crypt32.CryptProtectData
        function.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.c_wchar_p, ctypes.POINTER(_DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_DataBlob),
        ]
        function.restype = ctypes.c_int
        ok = function(ctypes.byref(input_blob), "QUANTNEX Owner Device private key",
                      ctypes.byref(entropy_blob), None, None, flags, ctypes.byref(output_blob))
    else:
        function = crypt32.CryptUnprotectData
        function.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(_DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_DataBlob),
        ]
        function.restype = ctypes.c_int
        description = ctypes.c_wchar_p()
        ok = function(ctypes.byref(input_blob), ctypes.byref(description),
                      ctypes.byref(entropy_blob), None, None, flags, ctypes.byref(output_blob))
        if description:
            kernel32.LocalFree(ctypes.cast(description, ctypes.c_void_p))
    # Keep input/entropy buffers alive until the native call has completed.
    _ = (input_buffer, entropy_buffer)
    if not ok:
        error = ctypes.get_last_error()
        raise OSError(error, "Windows could not protect or unlock the QUANTNEX Owner Device key.")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))


def _protect_private_key(raw_key: bytes) -> bytes:
    return _dpapi_transform(raw_key, protect=True)


def _unprotect_private_key(protected_key: bytes) -> bytes:
    return _dpapi_transform(protected_key, protect=False)


def _private_key_path(directory: Path) -> Path:
    return directory / "owner-device-key.dpapi"


def _claim_path(directory: Path) -> Path:
    return directory / "owner-device-claim.json"


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _load_or_create_private_key(directory: Path) -> Ed25519PrivateKey:
    path = _private_key_path(directory)
    if path.exists():
        stored = path.read_bytes()
        if not stored.startswith(PRIVATE_KEY_MAGIC):
            raise ValueError("The Owner Device key file has an unknown format; it was not overwritten.")
        raw_key = _unprotect_private_key(stored[len(PRIVATE_KEY_MAGIC):])
        try:
            return Ed25519PrivateKey.from_private_bytes(raw_key)
        except ValueError as exc:
            raise ValueError("The protected Owner Device key is invalid; it was not overwritten.") from exc

    private_key = Ed25519PrivateKey.generate()
    raw_key = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    protected = PRIVATE_KEY_MAGIC + _protect_private_key(raw_key)
    directory.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids silently replacing an identity if two first-run
    # setup processes happen to start together.
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        stored = path.read_bytes()
        if not stored.startswith(PRIVATE_KEY_MAGIC):
            raise ValueError("The Owner Device key file has an unknown format; it was not overwritten.")
        return Ed25519PrivateKey.from_private_bytes(_unprotect_private_key(stored[len(PRIVATE_KEY_MAGIC):]))
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(protected)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return private_key


def _write_claim(directory: Path, private_key: Ed25519PrivateKey, device_id: str) -> Path:
    payload = {
        "schema": CLAIM_SCHEMA,
        "product": PRODUCT,
        "device_id": device_id,
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    signature = base64.b64encode(private_key.sign(_canonical_json(payload))).decode("ascii")
    document = {"payload": payload, "signature": signature}
    destination = _claim_path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory,
                                         prefix=".owner-claim-", suffix=".tmp", delete=False) as stream:
            temporary_name = stream.name
            json.dump(document, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, destination)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return destination


def provision_owner_device(storage_directory: str | Path | None = None) -> dict[str, str]:
    """Create (or safely reuse) this Windows user's device identity and signed claim."""
    directory = Path(storage_directory) if storage_directory is not None else default_identity_directory()
    device_id = _machine_fingerprint()
    private_key = _load_or_create_private_key(directory)
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    claim_path = _write_claim(directory, private_key, device_id)
    return {
        "public_key_b64": base64.b64encode(public_key).decode("ascii"),
        "device_id": device_id,
        "claim_path": str(claim_path),
        "private_key_path": str(_private_key_path(directory)),
    }


def verify_owner_claim(
    claim_path: str | Path | None = None,
    pinned_public_key_b64: str = PINNED_OWNER_PUBLIC_KEY_B64,
    expected_device_id: str | None = None,
) -> bool:
    """Verify the signed claim against the pinned owner public key and this device."""
    if not pinned_public_key_b64:
        return False
    try:
        directory = Path(claim_path) if claim_path is not None else _claim_path(default_identity_directory())
        if directory.is_dir():
            directory = _claim_path(directory)
        document = json.loads(directory.read_text(encoding="utf-8"))
        payload = document["payload"]
        if payload.get("schema") != CLAIM_SCHEMA or payload.get("product") != PRODUCT:
            return False
        device_id = expected_device_id if expected_device_id is not None else _machine_fingerprint()
        if payload.get("device_id") != device_id:
            return False
        public_bytes = base64.b64decode(pinned_public_key_b64, validate=True)
        if len(public_bytes) != 32:
            return False
        signature = base64.b64decode(document["signature"], validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(public_bytes)
        public_key.verify(signature, _canonical_json(payload))
        return True
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False
    except Exception:
        # Invalid signatures and unavailable Windows identity services fail closed.
        return False


def is_owner_device() -> bool:
    """True only when a valid claim matches the public key pinned in the app."""
    return verify_owner_claim()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision the QUANTNEX Owner Device identity on this Windows laptop.")
    parser.add_argument("--provision", action="store_true", help="Create or reuse the protected Owner Device identity.")
    args = parser.parse_args(argv)
    if not args.provision:
        parser.error("Use --provision to create the Owner Device identity.")
    try:
        result = provision_owner_device()
    except Exception as exc:
        print(f"Owner Device setup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("QUANTNEX OWNER DEVICE IDENTITY CREATED")
    print("Device ID: " + result["device_id"])
    print("Public key (safe to share; this is NOT the private key):")
    print(result["public_key_b64"])
    print("Signed device claim saved locally: " + result["claim_path"])
    print("Protected private key saved locally: " + result["private_key_path"])
    print("IMPORTANT: Never upload, email, or share the .dpapi private-key file.")
    print("Owner access remains disabled until this public key is pinned in a reviewed QUANTNEX update.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
