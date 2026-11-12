# QUANTNEX Android

Native Android starter app built with Kotlin and Jetpack Compose.

## Requirements

- Android Studio with a compatible Android Gradle Plugin 8.7.3 toolchain
- JDK 17
- Android SDK Platform 35

## Build a debug APK

1. Open this `apps/android` folder in Android Studio.
2. Allow Gradle sync to finish.
3. Select **Build → Build Bundle(s) / APK(s) → Build APK(s)**.
4. The debug APK is normally created under `app/build/outputs/apk/debug/`.

The debug APK is for testing only. A public release APK must be built with a private signing key kept outside GitHub. Never commit signing keys or passwords.

## Phase 01 limitations

This app is a lightweight UI foundation. It does not request internet permissions, connect to a broker, fetch live prices, run bots, or place orders. Those capabilities require a secure backend and separate testing.
