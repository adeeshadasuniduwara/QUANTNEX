# QUANTNEX Android Releases

QUANTNEX publishes Android APK releases only. The release workflow does not build, attach or publish Windows executables.

## One-time signing setup

Every production APK must use the same private PKCS#12 signing keystore. If the signing key changes, Android will reject an in-place update and the user will have to uninstall the old app first.

Configure these GitHub repository Actions secrets:
- `ANDROID_KEYSTORE_BASE64`: base64-encoded PKCS#12 keystore.
- `ANDROID_KEYSTORE_PASSWORD`: keystore password.
- `ANDROID_KEY_ALIAS`: signing key alias.
- `ANDROID_KEY_PASSWORD`: signing key password.

Never commit the keystore or its passwords. If a signing key is lost, previously installed production APKs cannot be updated with a different key.

## Publish a release

After the signing secrets are configured and the Android build has passed:

1. Open the repository's **Actions** tab.
2. Select **QUANTNEX Android Release**.
3. Choose **Run workflow** and enter a version such as `v1.0.0`, or push a version tag beginning with `v`.
4. Wait for the signed APK build and checksum verification to complete.
5. Open **Releases** and confirm that the assets are `QUANTNEX-Android.apk` and `SHA256SUMS.txt`.

The release workflow fails early if signing credentials are missing. It intentionally does not publish an unsigned or differently signed APK as a production update.

## Android update behavior

- The app checks GitHub's latest release on launch and every five minutes while its workspace is active.
- An update is offered only when the release contains an APK asset and `SHA256SUMS.txt`.
- The app verifies the SHA-256 digest for the exact APK filename before opening Android's package installer.
- Android requires the user to approve installation. Ordinary apps cannot silently self-install.
- If the checksum is missing or invalid, the download fails, or the signature is incompatible, installation must not proceed.

## Telegram announcements

Telegram announcements are optional. Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` Actions secrets if the release should be announced. The bot must be allowed to post in the target chat/channel.

Never put bot tokens, API credentials or signing keys in source files, commits, issues or chat messages.
