# 📺 Telecamere

**A simple Tuya camera viewer for Android TV and compatible Fire TV devices.**

Telecamere brings your Tuya Smart / Smart Life cameras to the big screen. It is designed for people who want a quiet 2×2 camera wall controlled with a TV remote.

> This is an independent, community project. It is not affiliated with or endorsed by Tuya.

## ✨ What it does

- 🔐 Sign in with your Tuya email or phone number and password. No QR code or Tuya developer AppKey is required.
- 💾 Save sign-in details encrypted with Android Keystore so the app can sign in again when a session expires.
- 🏠 Show four silent SD previews edge to edge, with a visible focus border for remote navigation.
- 🧭 Order cameras by their names: **North**, **North East**, **East**, **South** (also recognizes **Nord**, **Nord Est**, **Est**, **Sud**). Other cameras follow in Tuya's original order.
- 🎥 Press OK/Select to open one camera full screen in HD with audio when the camera and device support it. If HD playback fails, the app falls back to SD.
- 🔄 Check GitHub for a newer stable release and offer to download it.

Camera names are used for ordering but are not shown on the camera wall. Use Page Up/Down to move between groups when your account has more than four cameras.

## 📺 Compatibility

- Android TV and Android-based Fire TV devices running **Android 7 / API 24 or newer**.
- ARMv7 and ARM64 APKs are included in each stable release.
- **Fire OS 5 is not supported**: it is based on Android 5.1 / API 22.
- **Vega OS devices are not supported** because they do not run Android APKs.

See Amazon's [Fire OS overview](https://developer.amazon.com/docs/fire-tv/fire-os-overview.html) and [Fire TV device list](https://developer.amazon.com/docs/device-specs/identify-fire-tv-devices.html) to check a device's platform.

## ⬇️ Install

1. Open [Releases](https://github.com/lohacker10/tuya-tv-viewer/releases/latest) and download the `Telecamere-vX.Y.Z.apk` asset.
2. Copy the APK to your TV or install it with ADB. Android may ask you to allow **Install unknown apps** for the app you used to open it.
3. Confirm the Android package installer prompt.
4. Open **Telecamere**, choose your account region, and sign in with your Tuya email/phone and password.

The first stable release uses a new signing key. If you are moving from the old beta, uninstall the beta before installing this release; Android will erase its saved data, so you will need to sign in again. Future stable releases use the same signing key and can be installed as updates.

## 🔄 Updates

At app startup, Telecamere checks GitHub's [latest stable release](https://docs.github.com/en/rest/releases/releases#get-the-latest-release). When an update is available, choose **Update** to download the APK. The app checks its SHA-256 checksum and opens Android's package installer.

Android requires permission to install packages from Telecamere and a confirmation for each update. It does not allow a regular app to install APK updates silently. See Android's [unknown app installation permission](https://developer.android.com/reference/android/content/pm/PackageManager#canRequestPackageInstalls()).

## 🎮 Remote controls

| Remote button | Action |
| --- | --- |
| Arrow keys | Move focus around the camera wall |
| OK / Select | Open the focused camera full screen |
| Back | Return to the four-camera wall |
| Page Up / Page Down | Change camera page |

The app supports H.264 and H.265 streams through the Tuya camera/portal playback paths. Resolution, audio, and playback stability depend on the camera, network, and Android decoder. The app streams live video and does not save recordings.

## 🔒 Privacy and security

- Tuya account credentials are encrypted on the device with Android Keystore and are used to authenticate with Tuya.
- The app connects to Tuya for account access and live camera streams, and to GitHub to check for app updates.
- The public repository does not contain account passwords, session cookies, real account-specific camera IDs, or the Android release-signing key.
- The source includes shared, app-level Tuya mobile protocol/signing constants recovered from the Tuya Smart Android app in [`const.py`](android/app/src/main/python/tuya_ipc_p2p_sdk/const.py). They are not user credentials or the release-signing key; like any client-side value, they can be inspected in the APK.
- Tuya's mobile and portal APIs used for live view are unofficial and may change. Use only accounts and cameras you are authorized to access.

## 🛠️ Build from source

Requirements: Flutter 3.41+, JDK 17, Android SDK/NDK, and Python 3.11.

```sh
flutter pub get
flutter analyze --no-pub
python -m unittest discover -s test -p 'test_*.py' -v
dart run test/fmp4_fragments_check.dart
flutter build apk --release --target-platform android-arm,android-arm64
```

A local build without the production signing environment uses Android's debug signing key. It is useful for testing, but it cannot update an APK signed by the project's production key.

## 📦 Releases and maintainers

GitHub Actions runs analysis, protocol tests, and an Android release build. To publish a new stable release, increment the version name and version code in `pubspec.yaml`. The workflow attaches the signed APK and its SHA-256 checksum to a GitHub Release.

The production signing key is stored in GitHub Actions Secrets, never in this repository. The workflow expects `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, and `ANDROID_KEY_PASSWORD`. Keep a secure backup of the signing key: losing it prevents in-place updates.

See [ATTRIBUTION.md](ATTRIBUTION.md) for third-party code and licensing notes.

