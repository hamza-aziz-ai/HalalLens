# HalalLens Mobile (Flutter)

> **Scaffold only.** This directory holds the Flutter platform runners (`android/`, `ios/`, `macos/`, ...), `pubspec.yaml` and a template test. There is **no `lib/` Dart source** (it was never committed), so the app cannot build or run yet. The instructions below describe the intended setup.

## Setup

1. Ensure Flutter is installed.
2. From this directory, run:
   ```bash
   flutter pub get
   ```
3. If the Android/iOS platform folders are missing, generate them once:
   ```bash
   flutter create .
   ```

## Run

```bash
flutter run
```

## Notes

- Base API URL is configured in `lib/core/services/app_config.dart`.
- Override API URL at build time:
  ```bash
  flutter run --dart-define=HALALLENS_API_BASE_URL=http://YOUR_IP:8001
  ```
- Authentication token storage uses `flutter_secure_storage`.
