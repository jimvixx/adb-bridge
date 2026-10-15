# Changelog

Notable project changes are tracked here using an **Unreleased** section and an initial documented baseline. Entries describe features in Git history; they are **not** claims that a GitHub Release or a version tag has been published.

`pyproject.toml` currently reports package version **0.1.0**. Do not infer a newer release number from feature merges alone.

## [Unreleased]

### Added

- Controlled APK installation (`install_apk`) with host directory, regular-file, size and SHA-256 checks.
- Explicit package/component launch allowlists (`launch_app`).
- Bounded `logcat` diagnostics and screenshot PNG artifacts.
- Emulator lifecycle inspection/start (`emulator_status`, `start_emulator`).
- Optional UI interactions (`tap`, `swipe`, constrained `keyevent`, and conservative text input).
- Unit and regression tests for lifecycle, UI validation and request handling.
- Generic documentation and a complete user/technical guide.

### Changed

- Emulator serial and AVD name are supplied by trusted host configuration rather than fixed to one development environment. Only one allowlisted emulator serial is supported per worker; physical-device serials remain rejected.
- App-specific sample configuration is removed in favor of `config/example.json`.
- The initial read-only bridge has evolved into an explicitly opt-in local emulator testing tool, with read-only operations enabled by default.

### Fixed

- Accept whitespace-separated device status lines from the ADB Smart Socket.
- Use `adb install --no-streaming -r` to avoid the earlier install argument error.
- Recognize QEMU emulator processes when checking configured AVD lifecycle state.

## [0.1.0] — Initial documented baseline

- Established the `adbbridge` Python package and `adbbridge` CLI.
- Introduced the local JSON request/response file queue and fixed `ping`, `status`, `devices` operations.
- Added basic host configuration, Linux user-service example, unit tests and Apache-2.0 licensing.

The `0.1.0` section reflects the project's initial changelog baseline; it does not assert a tagged public release.
