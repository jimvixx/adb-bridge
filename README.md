# ADBBridge

## Practical emulator MVP

The user service consumes JSON files from `%h/.gradle/adbbridge-queue`. It is deliberately limited to `emulator-5554`; no physical device, arbitrary shell command, or unrestricted ADB argument is supported. The shipped configuration enables only `ping`, `status`, and `devices`. `install_apk`, `launch_app`, `logcat`, `screenshot`, `tap`, `swipe`, `keyevent`, and `input_text` require explicit configuration opt-in. UI input is bounded to the configured display, a small key allowlist, and a conservative text alphabet.

This MVP has a simplified same-UID trust model: it protects against malformed AI-generated requests and accidental scope expansion, but does not isolate against a malicious process with the same user permissions or queue access. Device discovery uses the localhost ADB Smart Socket and does not auto-start ADB. The fixed subprocess ADB operations may cause the configured ADB client to auto-start the host ADB server; emulator state is never changed by the worker except when an explicitly enabled request is processed.
ADBBridge is a small host-side file-queue bridge for AI-assisted Android development. The host operator runs the trusted executable; an untrusted sandbox may write request files to a shared queue. Milestone 0 is deliberately read-only.

## Operations
Requests are JSON files in `QUEUE/requests`, with responses in `QUEUE/responses/ID.json`:
```json
{"id":"r1","op":"ping"}
{"id":"r2","op":"status","target":"emulator-5554"}
{"id":"r3","op":"devices"}
```
`id` is 1–80 characters matching `[A-Za-z0-9._:-]`. UI examples (only after explicit host configuration opt-in) are `{"id":"t1","op":"tap","target":"emulator-5554","x":100,"y":200}`, `{"id":"s1","op":"swipe","x1":100,"y1":200,"x2":100,"y2":500,"duration_ms":300}`, `{"id":"k1","op":"keyevent","keyevent":"BACK"}`, and `{"id":"i1","op":"input_text","text":"test 123"}`. Coordinates are integers inside `ui_width`/`ui_height`; duration is 1–10000 ms; keyevents are BACK, HOME, ENTER, or DEL; text is limited to 120 characters by default. Unknown fields fail closed. Responses have `{id,status,result}` or `{id,status:"error",error}`. Place requests using temporary-file + `fsync` + atomic rename; responses are atomic and mode 0600.

## Security boundaries
The queue is untrusted input. Keep the installed package, executable, and configuration outside sandbox-writable paths and owned by the host operator. The AI gets queue write access only. No arbitrary shell commands or ADB arguments, no `shell=True`, no ADB-server restart, no TCP listener, and an explicit device allowlist. UI operations can touch arbitrary screen locations once explicitly enabled, so test only synthetic content and never use them to press Send or contact real recipients. Queue approval data must never authorize a future mutation by itself.

## Install and migration
Do not rename or remove a running `smsecure-adb-agent` directory. This migration creates a sibling project and keeps the legacy project intact. The source checkout is development-only: production must use a normal, non-editable install in a host-owned directory. On the host:
```sh
cd /home/user/Repos/adb-bridge
python3 -m venv /home/user/.local/share/adbbridge/venv
/home/user/.local/share/adbbridge/venv/bin/python -m pip install --no-cache-dir .
install -d -m 700 /home/user/.gradle/adbbridge-queue/requests /home/user/.gradle/adbbridge-queue/responses
install -d -m 700 /home/user/.config/adbbridge
install -m 600 config/example.json /home/user/.config/adbbridge/config.json
chmod -R go-w /home/user/.local/share/adbbridge /home/user/.config/adbbridge
```
Edit the host-owned config allowlist, then install the unit outside the source checkout:
```sh
install -d -m 700 /home/user/.config/systemd/user
install -m 600 systemd/adbbridge.service /home/user/.config/systemd/user/adbbridge.service
```
The unit executes `/home/user/.local/share/adbbridge/venv/bin/adbbridge`, never the source checkout. It reads `/home/user/.config/adbbridge/config.json` and uses `/home/user/.gradle/adbbridge-queue`; only the queue is writable at runtime. Do not run the following until migration is approved:
```sh
systemctl --user daemon-reload
systemctl --user enable --now adbbridge.service
```
Cut over only after testing the new queue; stop the old service only if it is active, switch clients, and retain the old project for rollback. This milestone performs no cutover.

### Protection review

The sandbox may write only its configured Work roots; the source checkout, installed venv, host-owned config, and user systemd unit must not be among them. Verify this on the host with `stat` and `find` before deployment. The venv is a copy-based install, so later edits in the source checkout do not change the installed executable. Use owner-only permissions (`0700` directories, `0600` config/unit where practical), and do not grant the queue writer access to the venv, source, config, or unit. The queue is intentionally shared and untrusted; it must be the only AI-writable path.

## Development
`python3 -m unittest discover -s tests -v`

SMSecure is only `config/smsecure.json`; the core package has no SMSecure or ChatGPT Work dependency.
