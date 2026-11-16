import json

from app import owner_device


def install_test_dpapi(monkeypatch):
    monkeypatch.setattr(owner_device, "_protect_private_key", lambda value: b"test-protected:" + value)
    monkeypatch.setattr(owner_device, "_unprotect_private_key", lambda value: value.removeprefix(b"test-protected:"))
    monkeypatch.setattr(owner_device, "_machine_fingerprint", lambda: "machine-a")


def test_provision_creates_device_claim_and_only_exposes_public_key(tmp_path, monkeypatch):
    install_test_dpapi(monkeypatch)

    result = owner_device.provision_owner_device(tmp_path)

    private_file = tmp_path / "owner-device-key.dpapi"
    claim_file = tmp_path / "owner-device-claim.json"
    assert private_file.is_file()
    assert private_file.read_bytes().startswith(owner_device.PRIVATE_KEY_MAGIC + b"test-protected:")
    assert claim_file.is_file()
    assert result["device_id"] == "machine-a"
    assert len(result["public_key_b64"]) == 44  # Ed25519 raw public key is 32 bytes.
    assert owner_device.verify_owner_claim(
        claim_file, result["public_key_b64"], expected_device_id="machine-a"
    )


def test_provision_is_idempotent_and_does_not_replace_private_identity(tmp_path, monkeypatch):
    install_test_dpapi(monkeypatch)

    first = owner_device.provision_owner_device(tmp_path)
    original_private_file = (tmp_path / "owner-device-key.dpapi").read_bytes()
    second = owner_device.provision_owner_device(tmp_path)

    assert second["public_key_b64"] == first["public_key_b64"]
    assert (tmp_path / "owner-device-key.dpapi").read_bytes() == original_private_file
    assert owner_device.verify_owner_claim(
        tmp_path / "owner-device-claim.json",
        first["public_key_b64"],
        expected_device_id="machine-a",
    )


def test_owner_claim_fails_closed_without_pinned_public_key(tmp_path, monkeypatch):
    install_test_dpapi(monkeypatch)
    result = owner_device.provision_owner_device(tmp_path)

    assert not owner_device.verify_owner_claim(
        tmp_path / "owner-device-claim.json", "", expected_device_id="machine-a"
    )
    assert not owner_device.verify_owner_claim(
        tmp_path / "owner-device-claim.json", result["public_key_b64"], expected_device_id="different-machine"
    )


def test_tampered_owner_claim_is_rejected(tmp_path, monkeypatch):
    install_test_dpapi(monkeypatch)
    result = owner_device.provision_owner_device(tmp_path)
    claim_path = tmp_path / "owner-device-claim.json"
    document = json.loads(claim_path.read_text(encoding="utf-8"))
    document["payload"]["device_id"] = "attacker-machine"
    claim_path.write_text(json.dumps(document), encoding="utf-8")

    assert not owner_device.verify_owner_claim(
        claim_path, result["public_key_b64"], expected_device_id="attacker-machine"
    )


def test_unknown_private_key_format_is_never_overwritten(tmp_path, monkeypatch):
    install_test_dpapi(monkeypatch)
    private_file = tmp_path / "owner-device-key.dpapi"
    private_file.write_bytes(b"not-a-quantnex-key")

    try:
        owner_device.provision_owner_device(tmp_path)
    except ValueError as exc:
        assert "unknown format" in str(exc)
    else:
        raise AssertionError("An unknown identity file must not be overwritten.")

    assert private_file.read_bytes() == b"not-a-quantnex-key"


def test_non_windows_identity_fingerprint_fails_closed(monkeypatch):
    monkeypatch.setattr(owner_device.sys, "platform", "linux")
    try:
        owner_device._machine_fingerprint()
    except RuntimeError as exc:
        assert "requires Windows" in str(exc)
    else:
        raise AssertionError("Non-Windows systems must not create a Windows Owner Device identity.")
