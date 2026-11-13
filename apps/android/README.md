# QUANTNEX Android

A native Android shell that loads the same QUANTNEX Web workspace and adds Android navigation, workspace settings and release-update checks.

## Setup
1. Install the APK from the GitHub Actions artifact or a signed GitHub release.
2. Open QUANTNEX and enter the HTTPS URL of the hosted QUANTNEX Web workspace.
3. Use the native bottom bar for Overview, QUANTNEX VIEW, Trading Room, Journal and Updates.

A Windows PC localhost URL is not reachable from an Android phone. The web workspace must be hosted on an HTTPS server reachable by the phone. This Android shell does not expose the local-only desktop backend to the internet or copy local wallet/journal data.

## Updates
The app checks GitHub's latest release on launch. If that release contains an APK asset, the app downloads it and opens Android's package installer. Android requires the user to approve installation; silent self-install is not available to ordinary apps.

All production APK versions must use the same private signing key. Keep the key outside GitHub and configure secure release signing before publishing production updates. CI debug APKs are for testing and are not guaranteed to be update-compatible across different CI builds.

## Build
JDK 17, Android SDK 35, Android Gradle Plugin 8.7.3. From this directory run `gradle --no-daemon assembleDebug`.
