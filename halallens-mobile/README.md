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

- The base API URL is meant to live in `lib/core/services/app_config.dart`, which is not in this repository.
- Override API URL at build time:
  ```bash
  flutter run --dart-define=HALALLENS_API_BASE_URL=http://YOUR_IP:8001
  ```
- `pubspec.yaml` declares `flutter_secure_storage` for authentication token storage.
