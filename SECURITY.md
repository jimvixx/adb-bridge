# Security policy

ADBBridge is a **local development utility** for controlled Android emulator automation. It is not a strong isolation boundary, an authenticated remote execution service, or a general-purpose ADB proxy. The host operator decides which operations, emulator serial, applications and directories are allowed.

## Reporting a vulnerability

Please do **not** publish exploitable details, private logs or proof-of-concept payloads in a public issue. Use GitHub's private vulnerability reporting feature **if enabled** for this repository. Otherwise, open a brief issue requesting a private contact method **without including exploit details**. Include the affected revision, prerequisites, impact, reproducible steps and potential mitigations through the private channel.

The maintained development branch is `main`. Project metadata currently identifies version `0.1.0`; no guaranteed support window or patch SLA is offered.

## Intended trust model

- An isolated tool or AI agent has access to a **shared JSON queue**, not to unrestricted host ADB.
- A Python worker on the Linux host reads that queue and validates requests against an operator-controlled configuration.
- **Exactly one emulator serial** is permitted per worker and must be explicitly listed in `allowed_devices`; a serial other than the configured value is rejected. Physical-device serials are not accepted by the current validation.
- AVD lifecycle commands use the **host-configured** `emulator_avd` value, validated as a conservative AVD name; incoming requests cannot select other AVDs or flags.
- Only `ping`, `status`, and `devices` are enabled in the shipped configuration. Every other operation is opt-in.
- ADB subprocesses have fixed argument shapes with `shell=False`; there is no generic shell or arbitrary ADB-argument passthrough.

Changing serials or AVD names through **trusted host configuration** is an intended capability, not an authorization request from the queue. Changes require a worker restart.

## Guarantees and limitations

| Control | Scope and caveat |
| --- | --- |
| Request validation | Required ID / `op`, known field names, strict UI operation fields, basic type/range checks. Some non-UI operations currently accept unused *globally recognized* fields; do not rely on that behavior. |
| Emulator allowlist | One configured serial matching `emulator-NNNN`/`emulator-NNNNN`; no arbitrary physical device or remote serial. Serial identity depends on the host's ADB server. |
| App allowlist | `launch_app` checks exact package and component. `install_apk` currently checks path, SHA-256 and size, **not the APK's package identity or signing certificate**. |
| APK integrity | File hash is validated before invocation. This does **not** prevent replacement of a mutable file between hash verification and `adb install` (TOCTOU). |
| UI input | Coordinates bounded by configured dimensions, keyevents limited to `BACK`, `HOME`, `ENTER`, `DEL`, conservative ASCII text allowlist. An approved UI action may still send a message or perform a destructive action. |
| Logs/screenshots | Bounded output, but may expose sensitive content. Screenshots use a PNG signature check, not a complete decoder. |
| Filesystem | Worker sets request/response directories to `0700` and writes response/artifact files as `0600`; this does not isolate processes with the same UID. |
| ADB server | Discovery uses an existing localhost Smart Socket without starting ADB. Other fixed ADB CLI calls can **auto-start** the server if absent. A compromised host ADB server is out of scope. |
| Emulator status/start | Process identification is heuristic; lifecycle operations are opt-in. A worker service restart may terminate an emulator it launched in the same cgroup. |

**No per-request cryptographic authorization is implemented in `main`.** The experimental approval-broker work is not part of the supported runtime. A TTY confirmation by itself is not authenticated authorization.

## Deployment guidelines

1. Keep the installed worker, config and systemd unit **outside untrusted writable workspace roots**. Do not use an editable pip install for the production-like worker.
2. Use a private queue. Do not expose it through a public network share or public API endpoint.
3. Restrict operations to a disposable emulator and synthetic test data. Avoid real accounts, recipients and credentials.
4. Prefer an `artifact_directory` **inside a service-writable path**; the provided user service allows writes to the queue.
5. Review `systemd/adbbridge.service`: `ProtectHome=read-only` and `ProtectSystem=strict` are enabled. Emulator launch requires a carefully scoped writable AVD-data path, not wholesale removal of protections.
6. Restart the worker only at appropriate times: restarting the service may close the emulator it spawned.
7. Back up config and installed environment before changing permissions or upgrading.

## Privacy and diagnostics

`logcat`, screenshots, responses and APKs can contain phone numbers, message bodies, account data and other private information. Inspect and redact before sharing reports. If the active Android window sets `FLAG_SECURE`, screen capture may return a black image; that does not prove the application failed to render.

See the [User & Technical Guide](docs/USER_GUIDE.md) for deployment and protocol details.
