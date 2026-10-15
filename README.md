# ADBBridge

**Controlled Android emulator automation for sandboxed development tools and AI coding agents.**

ADBBridge connects an isolated development environment to the **host's existing Android Debug Bridge (ADB)** without exposing a general-purpose remote shell or unrestricted ADB command interface. An unprivileged producer writes JSON requests to a shared filesystem queue; a Python worker running on the Linux host validates each request against its own configuration and returns structured results.

**ADBBridge is application-agnostic.** Use it with any Android app whose APK, package and launch component you choose to allow. It is not tied to a particular messenger, build system, IDE, or AI provider.

> **Current scope:** one explicitly allowlisted **Android emulator serial** per worker, one optionally configured AVD, and a small set of known operations. This is not a general multi-device ADB proxy or a security boundary against arbitrary malicious code running under the host user's UID.

## Why?

An AI coding environment or isolated build tool may build an APK but be unable to connect to the Android Emulator running on a developer's desktop. Its network namespace may not have access to the host's ADB server on port 5037, and launching a second ADB server inside the sandbox may fail.

ADBBridge provides a small, observable bridge while keeping the ADB client, emulator executable, approved paths and device policy on the host.

```text
Isolated tool / AI agent                    Linux development host
┌──────────────────────┐                   ┌──────────────────────────┐
│ JSON request files   │── shared queue ──▶│ ADBBridge Python worker  │
│ JSON response files  │◀──────────────────│ Validate + enforce policy│
└──────────────────────┘                   │ Existing host ADB server │
                                         │ Android test emulator    │
                                         └──────────────────────────┘
```

No HTTP server, cloud account, vendor-specific integration, or application-specific backend is required.

## Features

| Category | Operations |
| --- | --- |
| Health & discovery | `ping`, `status`, `devices` |
| Emulator lifecycle | `emulator_status`, `start_emulator` |
| Application lifecycle | `install_apk`, `launch_app` |
| Diagnostics | `logcat`, `screenshot` |
| UI interaction | `tap`, `swipe`, `keyevent`, `input_text` |

- **Opt-in:** the supplied configuration enables only `ping`, `status` and `devices`.
- **Scoped target:** the worker operates on one emulator serial specified in `allowed_devices` (for example `emulator-5554`); physical devices and extra serials are rejected.
- **Fixed command forms:** UI and app operations do not accept arbitrary shell commands or ADB argument arrays.
- **Safety checks:** APK directory/size/SHA-256 validation, package/component allowlists, bounded output and timeouts, conservative text input and UI coordinate limits.
- **Local artifacts:** `screenshot` writes PNG files on the host and returns their paths.

## Requirements

- Linux with **Python 3.11+**, `venv`, Android SDK Platform Tools, and an accessible host ADB server.
- Optional Android Emulator and an **existing AVD** for `start_emulator`.
- A shared writable directory for producer requests and worker responses.
- Optional `systemd --user` for background operation.

## Quick start

```bash
git clone https://github.com/jimvixx/adb-bridge.git
cd adb-bridge

python3 -m venv "$HOME/.local/share/adbbridge/venv"
"$HOME/.local/share/adbbridge/venv/bin/python" -m pip install .

install -d -m 700 "$HOME/.config/adbbridge" \
  "$HOME/.gradle/adbbridge-queue/requests" \
  "$HOME/.gradle/adbbridge-queue/responses" \
  "$HOME/.gradle/adbbridge-queue/artifacts"
install -m 600 config/example.json "$HOME/.config/adbbridge/config.json"
```

Edit **`~/.config/adbbridge/config.json`** before starting: replace the illustrative `/home/your-user/...` paths, select the serial of *your* test emulator, and set the actual AVD name if you plan to enable lifecycle operations. Configuration is loaded by the host worker, **not from an incoming request**.

Run the worker in the foreground:

```bash
"$HOME/.local/share/adbbridge/venv/bin/adbbridge" \
  --queue "$HOME/.gradle/adbbridge-queue" \
  --config "$HOME/.config/adbbridge/config.json"
```

The [technical guide](docs/USER_GUIDE.md) explains the optional user-service deployment, permissions, writable AVD directories, and the full request protocol.

## First request

Publish the following JSON to `QUEUE/requests/ping-001.json` using a temporary file and an atomic rename:

```json
{"id":"ping-001","op":"ping"}
```

The worker writes a response to `QUEUE/responses/ping-001.json`:

```json
{"id":"ping-001","result":{"agent":"adbbridge","ok":true,"version":2},"status":"ok"}
```

The **request key is `op`, not `action`**. If using a device selector, use `target`, not `device`. AVD names, screenshot filenames and arbitrary ADB options are not accepted as request fields. See the [exact operation examples](docs/USER_GUIDE.md#7-operation-reference).

## Security and limitations

ADBBridge is intended for a **trusted local developer's machine**, with a sandbox-writable queue but a host-controlled executable and configuration. It guards against unsupported and malformed requests, but **does not enforce independent authentication between two processes with the same Unix UID**. Enabling UI actions can still trigger real actions in an app; use disposable emulators and synthetic data.

Other fixed ADB CLI operations may auto-start the host ADB server. Emulator start is opt-in and needs access to the host's graphical session and writable AVD data. Review [SECURITY.md](SECURITY.md) before enabling non-default operations.

## Project documentation

- [User & technical guide](docs/USER_GUIDE.md) — architecture, configuration, exact JSON schemas, installation, service operation, troubleshooting and rollback.
- [Security policy](SECURITY.md) — trust assumptions, limitations and responsible reporting.
- [Contributing](CONTRIBUTING.md) — development workflow, tests and PR guidelines.
- [Changelog](CHANGELOG.md) — project changes, distinct from published releases.

Run the unit tests with:

```bash
python3 -m unittest discover -s tests -v
```

## License

[Apache License 2.0](LICENSE).
