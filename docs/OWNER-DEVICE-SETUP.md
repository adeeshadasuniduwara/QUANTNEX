# QUANTNEX Owner Device Setup

## Purpose

This is the first stage of the Owner Device security rollout. It creates one Ed25519 identity on the owner's Windows laptop. The private key is protected by Windows DPAPI in the current Windows-user scope and is stored outside the QUANTNEX repository, so source updates and Git operations do not include it.

The signed claim also contains a SHA-256 fingerprint derived from the Windows MachineGuid. A copied claim cannot be used on a different Windows installation. The app must later verify the claim against the owner's public key pinned in a reviewed source update.

**Important:** This bootstrap alone does not yet enable or enforce Admin Mode. The backend remains in its existing local-only state until the follow-up authorization phase is implemented and reviewed. Do not expose the local API to a LAN or the public internet.

## One-time setup on the owner's Windows laptop

1. Update the local QUANTNEX source to the reviewed version containing `backend/app/owner_device.py`.
2. If this is the first launch, run `run_quantnex.bat` and choose option **1** once so the launcher creates `backend\\.venv` and installs the backend dependencies. You can close QUANTNEX after the setup finishes.
3. Open PowerShell in the QUANTNEX repository's `backend` folder.
4. Run:

   ```powershell
   .\\.venv\\Scripts\\python.exe -m app.owner_device --provision
   ```

5. The command prints a **Public key** and saves a signed device claim in:

   ```text
   %LOCALAPPDATA%\\QUANTNEX\\Owner\\owner-device-claim.json
   ```

6. Send only the printed public key to the QUANTNEX maintainer so it can be pinned in the reviewed source update.

## Never share these files

The private key is stored at:

```text
%LOCALAPPDATA%\\QUANTNEX\\Owner\\owner-device-key.dpapi
```

- Never paste, upload, email, commit, or send this `.dpapi` file.
- Never send the contents of the Owner folder.
- The public key printed by the setup command is safe to share.
- The signed claim is not a secret, but it is not needed in chat.

The command is idempotent: running it again on the same Windows user and machine reuses the existing private key instead of silently generating a replacement.

## Recovery notes

- Do not delete the Owner folder or the private-key file.
- Windows DPAPI protects the key for the current Windows user. Moving the file to another Windows account or another computer should make it unreadable.
- A Windows reinstall, new Windows user profile, or lost DPAPI key may require a deliberate owner-identity recovery process. Do not regenerate a key casually; a new public key requires a reviewed source update.
- This is a local-device identity, not a cloud account, remote access feature, or a way to control another person's computer.

## Security rollout status

- **Stage 1 — identity bootstrap:** creates a DPAPI-protected Ed25519 private key, machine-bound signed claim and shareable public key.
- **Stage 2 — authorization enforcement:** pin the reviewed owner public key; verify the claim at backend startup; require authenticated owner authorization for privileged APIs; add a separate public-user capability policy and UI gate.
- **Not yet implemented by Stage 1:** login/session enforcement, Admin UI restrictions, API authorization, remote account management or public deployment.
