# QUANTNEX Android

A native Android shell that loads the same QUANTNEX Web workspace and adds Android navigation, workspace settings and release-update checks.

## Setup
1. Install the APK from the GitHub Actions artifact or a signed GitHub release.
2. Open QUANTNEX and enter the HTTPS URL of the hosted QUANTNEX Web workspace.
3. Use the native bottom bar for Overview, QUANTNEX VIEW, Trading Room, Journal and Updates.

A Windows PC localhost URL is not reachable from an Android phone. The web workspace must be hosted on an HTTPS server reachable by the phone. This Android shell does not expose the local-only desktop backend to the internet or copy local wallet/journal data.

## Updates
The app checks GitHub's latest release on launch. If that release contains an APK asset, the app downloads it and opens Android's package installer. Android requires the user to approve installation; silent self-install is not available to ordinary apps.

All production APK versions must use the same private PKCS#12 signing keystore. Never commit the keystore. Configure these GitHub Actions repository secrets before publishing a release: `ANDROID_KEYSTORE_BASE64` (base64-encoded `.p12` file), `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, and `ANDROID_KEY_PASSWORD`. The release workflow builds and attaches `QUANTNEX-Android.apk` to the GitHub Release. The current CI debug APK uses a different debug signature; uninstall that test APK before installing the first production-signed APK. Later signed releases will be update-compatible as long as the same keystore is retained.

## Build
JDK 17, Android SDK 35, Android Gradle Plugin 8.7.3. From this directory run `gradle --no-daemon assembleDebug`.
