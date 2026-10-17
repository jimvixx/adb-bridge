# ADBBridge — User & Technical Guide

A practical reference for installing and operating **ADBBridge** on a Linux development host. ADBBridge provides a small JSON file-queue API for isolated tools that cannot directly access the host Android Debug Bridge (ADB) server.

**Current scope:** configurable emulator serial and AVD name, with one explicitly allowlisted emulator per worker. Physical devices, remote ADB targets and arbitrary shell commands remain unsupported. The installed worker reads its own host configuration; changing a source checkout does not update an already installed package.

See the [README](../README.md) for project rationale and [Security](../SECURITY.md) for the threat model.

## Contents

1. [Architecture](#1-architecture)
2. [Source and runtime layout](#2-source-and-runtime-layout)
3. [Requirements](#3-requirements)
4. [Install](#4-install)
5. [Host configuration](#5-host-configuration)
6. [Queue protocol](#6-queue-protocol)
7. [Operation reference](#7-operation-reference)
8. [systemd user service](#8-systemd-user-service)
9. [Integration workflow](#9-integration-workflow)
10. [Troubleshooting](#10-troubleshooting)
11. [Upgrade and rollback](#11-upgrade-and-rollback)
12. [Development and scope](#12-development-and-scope)

## 1. Architecture

```text
Sandboxed producer              Shared directory             Linux host user session
┌──────────────────────┐        ┌──────────────────────┐     ┌────────────────────────────┐
│ Writes JSON request  │───────▶│ queue/requests/*.json│────▶│ ADBBridge Python worker    │
│ Reads JSON response  │◀───────│ queue/responses/*.json◀────│ Config + request validation│
│ Uses artifact as allowed│     │ queue/artifacts/*.png│◀────│ Host ADB + Android Emulator│
└──────────────────────┘        └──────────────────────┘     └────────────────────────────┘
```

1. The operator starts the **host-side worker** with `--queue` and `--config`.
2. A tool/agent writes a JSON request file using a temporary file and atomic rename.
3. The worker polls `requests/*.json` (serial execution), checks the request and host allowlist, executes a **fixed** operation and writes `<id>.json` to `responses/`.
4. Screenshot requests additionally write a PNG to the configured `artifact_directory`, returning its absolute path in the response.
5. Files under `requests/` are removed after processing. Responses are not automatically garbage-collected.

`devices` connects to the existing host ADB Smart Socket at `127.0.0.1:5037`. Other Android operations run a configured ADB executable with a fixed argument vector (`shell=False`). `start_emulator` launches an allowlisted AVD using a fixed command. There is no HTTP API, general shell, direct remote network access, or dependency on any particular Android app.

## 2. Source and runtime layout

### Repository

```text
adb-bridge/
├── adbbridge/
│   ├── core.py                # Config, queue worker, ADB and emulator operations
│   ├── cli.py                 # Host command-line entry point
│   └── __init__.py
├── config/
│   └── example.json           # Generic read-only host example
├── systemd/
│   └── adbbridge.service      # Optional user service template
├── tests/
│   └── test_core.py           # Regression and portability tests
├── docs/
│   └── USER_GUIDE.md
├── .github/workflows/tests.yml
├── README.md
├── SECURITY.md
├── CONTRIBUTING.md
├── CHANGELOG.md
├── LICENSE
└── pyproject.toml
```

No project-specific `config/<app>.json` is shipped. Store your own package, APK and device settings in the **installed host config**, not in Git.

### Host paths used by the bundled unit

```text
~/.local/share/adbbridge/venv/          # Non-editable installed Python package
~/.config/adbbridge/config.json         # Local trusted configuration
~/.config/systemd/user/adbbridge.service
~/.gradle/adbbridge-queue/
├── requests/
├── responses/
└── artifacts/                           # Example artifact_directory
~/.android/avd/                         # Android Emulator state (not part of bridge)
```

The CLI can take another queue/config path, but the **bundled systemd unit** uses the locations above. Adapt the unit for a different layout. The source checkout is not the installed runtime.

## 3. Requirements

- Linux and Python **3.11+**, with `venv`/`pip`.
- Android SDK Platform Tools (`adb`), and a **host ADB server** for discovery and online checks.
- For `start_emulator`: Android Emulator executable and an AVD created ahead of time, plus a working GUI session.
- A directory shared between the sandboxed producer and host worker.
- Optional user-level systemd.

Discover valid device serials and AVD names **in a normal host terminal**:

```bash
"$HOME/Android/Sdk/platform-tools/adb" devices -l
"$HOME/Android/Sdk/emulator/emulator" -list-avds
```

An ADB emulator serial such as `emulator-5554` is **not** an AVD name. An AVD such as `Pixel_API_35` is **not** the name of an Android application. You must configure both separately when using emulator lifecycle operations.

## 4. Install

All commands below run on the **Linux host**, not inside an isolated development sandbox.

### 4.1 Obtain and install the program

```bash
git clone https://github.com/jimvixx/adb-bridge.git
cd adb-bridge

python3 -m venv "$HOME/.local/share/adbbridge/venv"
"$HOME/.local/share/adbbridge/venv/bin/python" -m pip install --no-cache-dir .
"$HOME/.local/share/adbbridge/venv/bin/adbbridge" --help
```

A regular, **non-editable** install avoids having a running host service import Python code directly from an AI-writable checkout. `pip install -e .` is appropriate only for a dedicated development virtual environment.

### 4.2 Initialize directories and configuration

```bash
install -d -m 700 "$HOME/.config/adbbridge" \
  "$HOME/.gradle/adbbridge-queue/requests" \
  "$HOME/.gradle/adbbridge-queue/responses" \
  "$HOME/.gradle/adbbridge-queue/artifacts"

install -m 600 config/example.json "$HOME/.config/adbbridge/config.json"
```

**Edit** the installed JSON: replace the illustrative `/home/your-user/...` paths and select the actual emulator serial. Values inside JSON do **not** expand `$HOME` or `~` automatically. Choose `artifact_directory` inside a path the service may write.

### 4.3 Foreground operation

```bash
"$HOME/.local/share/adbbridge/venv/bin/adbbridge" \
  --queue "$HOME/.gradle/adbbridge-queue" \
  --config "$HOME/.config/adbbridge/config.json"
```

CLI flags:

| Flag | Behavior |
| --- | --- |
| `--queue PATH` | Required queue root |
| `--config PATH` | Required host JSON configuration |
| `--once` | Consume currently queued requests and exit |
| `--interval SECONDS` | Polling interval in continuous mode; default `0.25` |

Do not start two workers against the **same queue** concurrently.

## 5. Host configuration

The **host** controls the selected emulator, AVD, allowable APK paths, package names, components and permitted operations. Requests cannot change the config.

### 5.1 Generic config example

```json
{
  "adb": "/home/your-user/Android/Sdk/platform-tools/adb",
  "host": "127.0.0.1",
  "port": 5037,
  "allowed_devices": ["emulator-5554"],
  "emulator": "/home/your-user/Android/Sdk/emulator/emulator",
  "emulator_avd": "Pixel_API_35",
  "artifact_directory": "/home/your-user/.gradle/adbbridge-queue/artifacts",
  "allowed_apk_directories": [],
  "allowed_packages": [],
  "allowed_components": {},
  "permitted_operations": ["ping", "status", "devices"],
  "command_timeout_seconds": 15,
  "ui_width": 1080,
  "ui_height": 1920,
  "max_input_text": 120
}
```

This example is safe-by-default: application/UI/lifecycle actions are **disabled**. Replace values for your machine; these paths are illustrative. If your host ADB server uses a different emulator serial (for example `emulator-5556`), replace `allowed_devices` with a one-element list containing that serial. The worker does **not** choose whichever device happens to be connected.

### 5.2 Adding an application

For your own debug application, edit the private host config:

```json
{
  "allowed_apk_directories": ["/home/your-user/Projects/ExampleApp/app/build/outputs/apk/debug"],
  "allowed_packages": ["com.example.app"],
  "allowed_components": {
    "com.example.app": ["com.example.app/.MainActivity"]
  }
}
```

These are **fragments**, not a replacement for the full JSON. Merge them into the original host config. Determine the real package and launcher from your own APK rather than assuming every app uses `.MainActivity`.

Only add `install_apk`, `launch_app` or UI actions to `permitted_operations` if you intend to authorize them on that test emulator. The currently implemented install operation verifies file integrity/path but **does not check the APK's declared package or signer**.

### 5.3 Configuration keys

| Key | Default / restriction | Purpose |
| --- | --- | --- |
| `allowed_devices` | **Required**: exactly one `emulator-NNNN` or `emulator-NNNNN` serial | Select the only authorized ADB emulator for this worker |
| `adb` | `$HOME/Android/Sdk/platform-tools/adb` | Host Android Platform Tools executable; use an absolute path |
| `host` | `127.0.0.1` only | Existing host ADB Smart Socket |
| `port` | `5037`, valid 1–65535 | Host Smart Socket TCP port |
| `permitted_operations` | `ping`, `status`, `devices` | Explicit enablement; these three always required |
| `emulator` | `$HOME/Android/Sdk/emulator/emulator` | Host Android Emulator executable |
| `emulator_avd` | Optional unless `emulator_status` or `start_emulator` is enabled | AVD name, 1–80 characters from `A–Z`, `a–z`, `0–9`, `_`, `-`, `.`; begins alphanumeric |
| `emulator_boot_timeout_seconds` | 45; 1–300 | Returned by `start_emulator`; caller must still poll |
| `allowed_apk_directories` | `[]` | Canonical directory roots for APK installation |
| `max_apk_bytes` | 200 MiB | Upper bound checked before installation |
| `allowed_packages` | `[]` | Package names allowed for `launch_app` |
| `allowed_components` | `{}` | Exact launch components per package |
| `artifact_directory` | `$HOME/.gradle/adbbridge-artifacts` | PNG output; choose a service-writable directory |
| `max_screenshot_bytes` | 16 MiB | Maximum screencap response length |
| `command_timeout_seconds` | 15; **1–60** | Socket/ADB command timeout |
| `max_response_bytes` | 1 MiB; 1024–16 MiB | Response size bound |
| `ui_width`, `ui_height` | 1080, 1920; 1–10000 | Maximum allowed UI coordinates |
| `max_input_text` | 120; 1–1000 | Maximum text length, additionally subject to character allowlist |
| `DISPLAY`, `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR` | Inherit host environment unless configured | Optional graphical-environment overrides for emulator |

**Compatibility:** `allowed_devices` and `emulator_avd` are configurable in the current implementation. After upgrading the source checkout, separately update the installed worker and verify its configuration via `status`.

**Service lifecycle:** the worker reads config at startup. Restart to apply updates, at a time when a child emulator may be safely stopped. Changes to the systemd **unit** also require `systemctl --user daemon-reload`.

### 5.4 Enable operations (host only)

Make a backup first and edit the trusted config. For example, enable `screenshot` without disabling existing entries:

```bash
CONFIG="$HOME/.config/adbbridge/config.json"
cp -a "$CONFIG" "$CONFIG.backup-$(date +%Y%m%d-%H%M%S)"
python3 - <<'PY'
import json
from pathlib import Path
path = Path.home() / '.config/adbbridge/config.json'
config = json.loads(path.read_text())
config['permitted_operations'] = sorted(set(config['permitted_operations']) | {'screenshot'})
path.write_text(json.dumps(config, indent=2) + '\n')
PY
chmod 600 "$CONFIG"
```

The queue cannot enable a disabled operation. Always check `status` after the worker restarts.

## 6. Queue protocol

### 6.1 Request and response shapes

Requests are **JSON objects**, placed in `<queue>/requests/*.json`:

```json
{"id":"ping-001","op":"ping"}
```

Required keys: `id` (1–80 characters, alphabet `[A-Za-z0-9._:-]`) and `op`. An optional `target` must equal the single configured emulator serial; when omitted, the configured serial is used.

The names **`action`** and **`device`** are not valid replacements for `op` and `target`. Do **not** add `avd` to `start_emulator` or `artifact` to `screenshot`: the former comes from host configuration and the latter is derived from request `id`.

Success example:

```json
{"id":"ping-001","status":"ok","result":{"agent":"adbbridge","ok":true,"version":2}}
```

Error example:

```json
{"id":"bad-001","status":"error","error":{"code":"schema_invalid","message":"unknown request field"}}
```

**Check both status and process result:** `status: "ok"` means the request handler returned normally. An ADB subprocess may still have **`result.exit_code != 0`** and an error in stderr. Check those fields on install/launch/logcat/UI commands.

Use unique IDs; a repeated ID can overwrite an old response. The worker removes processed requests but does not automatically delete old response files or screenshots. Responses are atomically replaced with mode `0600`; the queue directories are set `0700`.

### 6.2 Submit atomically (Python standard library)

```bash
python3 - <<'PY'
import json, os, tempfile, uuid
from pathlib import Path
queue = Path.home() / '.gradle/adbbridge-queue'
rid = 'ping-' + uuid.uuid4().hex
fd, tmp = tempfile.mkstemp(prefix='.request-', suffix='.tmp', dir=queue / 'requests')
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump({'id': rid, 'op': 'ping'}, f)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, queue / 'requests' / f'{rid}.json')
finally:
    Path(tmp).unlink(missing_ok=True)
print(queue / 'responses' / f'{rid}.json')
PY
```

Poll the printed response file path, parse it, and verify its `id`. This is a file-queue protocol, not stdin commands to the running worker.

### 6.3 Sandboxed clients and filesystem permissions

ADBBridge is independent of any particular AI agent, IDE or sandbox. It **does not require a ChatGPT Work, Codex or application-specific permission profile**. Its file-queue transport does, however, require filesystem access on *both* sides:

| Actor | Required access |
| --- | --- |
| Request producer (AI agent, test runner or other client) | Create a temporary JSON file and atomically rename it into `<queue>/requests/`; read `<queue>/responses/<id>.json`; read `<artifact_directory>` if consuming screenshots. |
| Host ADBBridge worker | Read and remove requests, create responses and artifacts, and access host ADB/emulator executables as configured. |

The worker's `systemd` `ReadWritePaths` allowance applies **only to that service**. It does not grant permission to the sandboxed producer. Conversely, giving the producer write access to the queue does not grant unrestricted host filesystem access or direct ADB access. It **does** allow the producer to invoke any operation already enabled in the host allowlist; treat queue write access as a meaningful capability.

A queue located outside the producer's writable workspace (for example `~/.gradle/adbbridge-queue`) may be readable but not writable. In a filesystem sandbox, a failed request-file creation can report **`Read-only file system`** even when the Unix ownership and mode bits would normally permit writes. Do not try to fix a sandbox mount restriction with `chmod 777`, `sudo`, or by disabling the sandbox. Instead, use a supported, narrowly scoped filesystem approval, configure a suitable client-specific permission for the queue, or choose a shared queue location that both the client and worker can access without weakening the host policy.

**ChatGPT Work / Codex (tested optional integration).** A follow-up Linux test was completed **after removing the entire application-specific `smsecure-local` profile** from `~/.codex/config.toml` and rebooting the host. The Codex configuration retained `default_permissions = ":workspace"`; a new ChatGPT Work session used **Approve for me**. This was an end-to-end check of the *absence* of the custom profile, rather than merely leaving it unselected.

| Capability | Standard `:workspace` sandbox | With Work's supported approval mechanism |
| --- | --- | --- |
| Read ADBBridge repository | Allowed in the tested session | Not needed |
| Read test application repository | Allowed in the tested session | Not needed |
| Create/delete a temporary file in the test application repository | Denied: `Read-only file system` | Succeeded |
| Read ADBBridge queue | Allowed | Not needed |
| Write to ADBBridge queue | Denied: `Read-only file system` | Succeeded |
| Submit fresh `ping` and `status` through the queue | Not possible without queue write access | Both passed (`status: "ok"`, matching response IDs) |

The test created and removed harmless temporary files, then verified that both repositories had clean Git working trees and that probe files and test responses had been removed. No Android device, emulator, app, service or ADB configuration was changed. The earlier on-demand approval test **did not display an interactive prompt**: additional access was automatically granted under **Approve for me**. Do not infer from that observation that access will be approved automatically, retained between sessions or available in every installation.

**Result:** ADBBridge does **not** require `smsecure-local`, any other named custom Codex permission profile, or a project-specific network permission. The proven requirement is narrower: the producer must be able to create requests and read responses in the configured queue, either within its normal writable scope or after a client-supported approval. Standard `:workspace` *alone* did **not** permit queue writes at the tested path. This test does not establish that every other Work session or third-party client will have the same filesystem access.

For reliable setup:

1. Verify the client can **write atomically** under `<queue>/requests` and read `<queue>/responses` (and screenshots if needed), not merely list the queue directory.
2. If access is denied, use the client's supported approval mechanism or narrowly scoped permission configuration. Avoid global write grants for unrelated source trees or home directories.
3. Submit `ping` and `status` using the exact schemas above, and verify fresh response IDs. These checks require no emulator or SMS/MMS interaction.
4. Keep the host worker's separate allowlists and systemd restrictions in place; producer permissions are **not** a substitute for ADBBridge request validation.

ADBBridge does not read `~/.codex/config.toml` and has no dependency on its contents. **Do not remove required Codex configuration keys or change global permission defaults just to enable ADBBridge.** If you choose to change client settings, follow the instructions for your installed client version, back up the configuration, and verify a clean application start after a full host reboot if needed. The successful `:workspace` test above is an observation about one client environment, **not** an ADBBridge setup requirement.

## 7. Operation reference

Examples use a **sample device** `emulator-5554`, sample AVD `Pixel_API_35`, and sample Android package `com.example.app`. Replace them in host configuration as appropriate. `op` names and required fields are exact; extra unknown request fields are rejected, and UI operation fields are additionally scoped per operation.

### Health and discovery

#### `ping` — enabled by default

```json
{"id":"ping-01","op":"ping"}
```

Reports worker identity and queue protocol version (`version: 2`, not the Python package version).

#### `status` — enabled by default

```json
{"id":"status-01","op":"status"}
```

Shows permitted operations, selected device and queue. This is the most reliable way to inspect the **installed running worker** policy.

#### `devices` — enabled by default

```json
{"id":"devices-01","op":"devices","target":"emulator-5554"}
```

Requests `host:devices-l` from the **already running** ADB server on loopback and lists only the configured serial. `device` state does not prove Android has completed boot.

### Emulator lifecycle

#### `emulator_status` — opt-in

```json
{"id":"avd-state-01","op":"emulator_status"}
```

Returns `avd`, `process`, `adb_state`, `boot_completed`, `state` (`stopped`, `booting`, `ready`), and optional `adb_error`. Process detection uses a heuristic over `emulator` and `qemu-system-*` command lines containing the **configured AVD name**. `ready` requires `sys.boot_completed=1` on the selected serial.

#### `start_emulator` — opt-in

```json
{"id":"avd-start-01","op":"start_emulator"}
```

Runs a fixed command with host-configured executable and AVD:

```text
<emulator> -avd <configured-avd> -gpu swiftshader_indirect -no-snapshot -no-boot-anim -no-audio
```

It immediately returns `started: true, state: "starting"` or a result such as `already_running`/`already_ready`. This is **not a blocking boot wait**: poll `emulator_status` until ready; never repeatedly start the same AVD during boot. Graphics flags are fixed by the current implementation, not request-controlled.

### Application lifecycle

#### `install_apk` — opt-in

```json
{
  "id":"install-01",
  "op":"install_apk",
  "target":"emulator-5554",
  "apk_path":"/home/your-user/Projects/ExampleApp/app/build/outputs/apk/debug/app-debug.apk",
  "sha256":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

The SHA-256 above is **illustrative**. Calculate the hash of your actual APK with `sha256sum`. The file must be a regular file (not a symlink) under `allowed_apk_directories`, within `max_apk_bytes`, and match the supplied digest. Then ADBBridge invokes:

```text
adb -s <configured-serial> install --no-streaming -r <checked-apk-path>
```

The installer **does not bind the APK's package identity or signer** to `allowed_packages`. Protect the APK path from modification between verification and installation (TOCTOU). Installation may replace an installed app; do not use on real devices.

#### `launch_app` — opt-in

```json
{
  "id":"launch-01",
  "op":"launch_app",
  "target":"emulator-5554",
  "package":"com.example.app",
  "component":"com.example.app/.MainActivity"
}
```

Requires both package and full component to appear in the host allowlists; executes a fixed `am start -n` command. Check screenshot/logcat to confirm the UI rendered.

### Diagnostics

#### `logcat` — opt-in

```json
{"id":"log-01","op":"logcat","target":"emulator-5554","lines":200}
```

Optional `lines`: integer 1–2000, default 200. Optional `since`: up to 40 characters, passed as `adb logcat -T <since>`. Output is bounded by configured response size and timeout. `logcat` can contain sensitive information; treat it accordingly.

#### `screenshot` — opt-in

```json
{"id":"shot-01","op":"screenshot","target":"emulator-5554"}
```

Runs `exec-out screencap -p`, checks PNG signature/size, writes `<artifact_directory>/shot-01.png`, and returns `artifact_path` and byte length. **There is no request `artifact` field.** An app with `FLAG_SECURE` may produce a black capture; that is not necessarily a rendering failure. Producer access to the returned artifact path depends on sandbox file permissions.

### UI automation (all opt-in)

#### `tap`

```json
{"id":"tap-01","op":"tap","target":"emulator-5554","x":120,"y":200}
```

`x`,`y`: integers from zero up to but excluding `ui_width`/`ui_height`. Only tap observed coordinates from a fresh screenshot.

#### `swipe`

```json
{"id":"swipe-01","op":"swipe","target":"emulator-5554","x1":100,"y1":500,"x2":100,"y2":200,"duration_ms":300}
```

All coordinates are bounded. Optional duration: integer **1–10000 ms**, default 300. Perform only on an observed safe scrollable region.

#### `keyevent`

```json
{"id":"back-01","op":"keyevent","target":"emulator-5554","keyevent":"BACK"}
```

Allowed values: `BACK`, `HOME`, `ENTER`, `DEL` only. Even `ENTER` can activate a focused button; verify the UI state before using it.

#### `input_text`

```json
{"id":"text-01","op":"input_text","target":"emulator-5554","text":"Test 123"}
```

Text must be nonempty, <= configured `max_input_text` (default 120) and match ASCII letters, digits, spaces or `.,!?@_+-`. No arbitrary Unicode or shell metacharacters. A zero subprocess exit code does not guarantee the correct field received the text: verify screenshots. Use synthetic text and **never press Send** in a real conversation without specific approval.

### Operation matrix

| Operation | Default | Extra keys beyond `id` and `op` | Side effects |
| --- | --- | --- | --- |
| `ping` | enabled | none | none |
| `status` | enabled | none | reads config summary |
| `devices` | enabled | optional `target` | reads ADB state |
| `emulator_status` | opt-in | optional `target` | reads host/device state |
| `start_emulator` | opt-in | optional `target` | starts AVD |
| `install_apk` | opt-in | `apk_path`, `sha256`; optional `target` | installs/replaces app |
| `launch_app` | opt-in | `package`, `component`; optional `target` | launches app |
| `logcat` | opt-in | optional `lines`, `since`, `target` | reads sensitive logs |
| `screenshot` | opt-in | optional `target` | writes PNG |
| `tap` | opt-in | `x`, `y`; optional `target` | UI action |
| `swipe` | opt-in | `x1`,`y1`,`x2`,`y2`; optional `duration_ms`,`target` | UI gesture |
| `keyevent` | opt-in | `keyevent`; optional `target` | UI action |
| `input_text` | opt-in | `text`; optional `target` | UI text entry |

## 8. systemd user service

The bundled `systemd/adbbridge.service` is a **user** service running as the host desktop account, not a privileged system daemon:

```ini
[Unit]
Description=ADBBridge controlled emulator development bridge
[Service]
Type=simple
WorkingDirectory=%h/.local/share/adbbridge
ExecStart=%h/.local/share/adbbridge/venv/bin/adbbridge --queue %h/.gradle/adbbridge-queue --config %h/.config/adbbridge/config.json
Restart=on-failure
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=%h/.gradle/adbbridge-queue
[Install]
WantedBy=default.target
```

Install once from the repository:

```bash
install -D -m 600 systemd/adbbridge.service \
  "$HOME/.config/systemd/user/adbbridge.service"
systemctl --user daemon-reload
systemctl --user enable --now adbbridge.service
systemctl --user status adbbridge.service --no-pager -l
```

View recent errors:

```bash
journalctl --user -u adbbridge.service -n 100 --no-pager -l -o cat
systemctl --user show-environment | grep -E '^(DISPLAY|WAYLAND_DISPLAY|XDG_RUNTIME_DIR|XAUTHORITY)='
```

**AVD write access:** The emulator typically needs to write under `~/.android/avd`. Since the template restricts writes to the queue, an explicitly enabled `start_emulator` may require a narrowly scoped user-systemd override:

```bash
install -d -m 700 "$HOME/.config/systemd/user/adbbridge.service.d"
cat > "$HOME/.config/systemd/user/adbbridge.service.d/20-emulator.conf" <<'EOF'
[Service]
ReadWritePaths=%h/.android
EOF
systemctl --user daemon-reload
```

Verify the actual AVD data location, systemd namespace behavior, and writable path before adding the override. Do not blindly disable `ProtectHome` or `ProtectSystem`. An emulator launched by this unit can be terminated with it during `systemctl --user restart` even when it is running in a separate process session.

## 9. Integration workflow

Recommended order for an AI/sandbox workflow:

1. `ping` and `status` via the queue: confirm correct installed worker and enabled operations.
2. `emulator_status` if enabled; `start_emulator` **once** if stopped; poll status until `ready`.
3. `devices` to confirm the configured target is visible as `device`.
4. Build a **debug-only** APK in your own application repo, validate its hash and path, then opt-in to `install_apk` if appropriate.
5. `launch_app` using the package/component from the **actual APK**.
6. Capture `screenshot` to confirm the displayed UI; inspect `logcat` for bounded crash evidence.
7. With explicit UI opt-in, use a screenshot-derived `tap`, synthetic `input_text`, bounded `swipe` or `keyevent`. Verify each step by screenshot; do not automate real sends, payments, deletion or destructive operations.

AI tool requests should use **only the shared queue**. Do not call `adb` inside a restricted network namespace: it may try and fail to start its own ADB server.

## 10. Troubleshooting

| Symptom | Check / response |
| --- | --- |
| `operation_denied` for apparently enabled operation | Use **`op`**, not `action`; run `status` to verify the *installed* config. Wrong operation name is treated as denied. |
| `schema_invalid` | Remove unsupported fields (`artifact`, `device`, `action`, `avd`, `wait`). Use exact examples above. |
| `config_invalid` on launch | Confirm exactly one `allowed_devices` emulator serial and (for lifecycle operations) a valid `emulator_avd`; check JSON types and timeout `1–60`. |
| `server_unavailable` | Confirm host ADB listens on `127.0.0.1:5037`. Sandbox loopback is not necessarily host loopback. |
| Emulator reports `stopped` while GUI is visible | Check later `emulator_status`; process detection is heuristic (`qemu-system-*`/`emulator`) and ADB may be coming online. |
| Emulator starts but exits | Inspect user journal; check host graphics environment, permissions on AVD data and emulator CLI capabilities. |
| `device_unavailable` | Wait for ADB `device` state; whitespace in `devices -l` is parsed with generic whitespace splitting. |
| `Unable to open file: -S` on APK install | Current implementation uses fixed `install --no-streaming -r` to avoid the previous erroneous `--` separator. Check installed version. |
| Black PNG | May be app's Android `FLAG_SECURE` setting; compare home screen capture. |
| `status: ok` but install/launch failed | Inspect `result.exit_code` and `result.stderr`. |
| `input_text` fails | Check conservative alphabet, text length and target field focus. |
| Producer can read queue but writes fail with `Read-only file system` | This can be a **producer sandbox mount restriction**, not Unix file-mode permissions or the worker allowlist. Request narrowly scoped client-side filesystem approval or use an allowed shared queue location; see [Sandboxed clients and filesystem permissions](#63-sandboxed-clients-and-filesystem-permissions). |
| Screenshot path is inaccessible to AI tool | Artifact is on host; export a copy into a designated accessible directory, not by broadening all home permissions. |

## 11. Upgrade and rollback

Back up the real host configuration and installed environment **before** upgrading:

```bash
BACKUP="$HOME/.config/adbbridge/backups/pre-update-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP"
cp -a "$HOME/.config/adbbridge/config.json" "$BACKUP/config.json"
cp -a "$HOME/.config/systemd/user/adbbridge.service" "$BACKUP/adbbridge.service"
tar -czf "$BACKUP/venv.tar.gz" -C "$HOME/.local/share/adbbridge" venv
printf 'Backup: %s\n' "$BACKUP"
```

Upgrade from a **reviewed Git checkout**, ideally with the emulator stopped so service restart cannot close a running AVD:

```bash
cd ~/Repos/adb-bridge
python3 -m unittest discover -s tests -v
systemctl --user stop adbbridge.service
"$HOME/.local/share/adbbridge/venv/bin/python" -m pip install --no-cache-dir .
systemctl --user reset-failed adbbridge.service
systemctl --user start adbbridge.service
systemctl --user is-active adbbridge.service
```

Rollback must restore the **previous installation**, not merely uninstall the program. With the service stopped, restore the saved config and venv from your named backup, then start the service. **Do not overwrite an active venv**, and do not delete data or queue artifacts during an ordinary rollback.

## 12. Development and scope

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q adbbridge tests
git diff --check
```

CI runs Python 3.11 unit tests. Unit mocks verify request handling and fixed argv; **they do not replace real emulator integration tests**. A fresh manual integration test should verify the configured AVD/serial, including alternative values where possible, and should preserve user data.

ADBBridge intentionally remains **one-emulator-at-a-time**, even though its selected emulator and AVD are now configurable. Support for multiple simultaneous emulators, arbitrary real Android devices, a general device command shell, and authenticated cross-UID approval infrastructure are **not implemented**. There is no dependency on any particular Android application or AI service.
