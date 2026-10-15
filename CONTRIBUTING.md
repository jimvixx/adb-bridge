# Contributing to ADBBridge

ADBBridge aims to remain a **small, generic, controlled bridge** between isolated development tools and Android emulators on Linux. Contributions should be focused, testable and justified by real development needs, rather than adding a broad remote-execution framework.

## Development setup

Prerequisites: Python **3.11+**, Git and (optionally) Android SDK tools for manual integration testing.

```bash
git clone https://github.com/jimvixx/adb-bridge.git
cd adb-bridge
python3 -m venv .venv
.venv/bin/python -m pip install -e .
python3 -m unittest discover -s tests -v
python3 -m compileall -q adbbridge tests
git diff --check
```

An editable development install is fine in a trusted local checkout. For a worker that processes untrusted queue files, use a **non-editable** install in a host-controlled directory and a separately maintained config.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `adbbridge/core.py` | Config validation, file-queue processing and fixed Android operations |
| `adbbridge/cli.py` | Command-line entry point |
| `tests/` | Unit and regression tests, mostly mocked |
| `config/example.json` | Generic, read-only-by-default sample host config |
| `systemd/adbbridge.service` | Optional Linux user service |
| `docs/USER_GUIDE.md` | Operator guide and protocol reference |
| `.github/workflows/tests.yml` | Python unit-test CI |

Application-specific sample policies **do not belong in the main repository**. Configure package names, APK paths and AVD names in your private host config.

## Contribution checklist

- Start from updated `main` on a focused branch.
- Explain the use case, changes, and compatibility impact in your PR.
- Keep all existing operations functional; don't widen defaults or remove allowlist checks.
- For new operations, document every accepted request field and test invalid/unknown fields, disabled operations, unsupported device targets, timeouts and host-process failures.
- Never allow arbitrary shell, remote shell scripts, ADB arguments or arbitrary physical devices.
- Keep per-host details (personal usernames, absolute APK paths, AVD names, real package names, screenshots) out of tracked examples.
- Update `README.md` when scope changes, `docs/USER_GUIDE.md` when protocol/config changes, `SECURITY.md` when the trust model changes, and `CHANGELOG.md` under **Unreleased**.
- Confirm `python3 -m unittest discover -s tests -v` and `git diff --check` pass. Describe any manual integration tests separately from unit tests.

## Request protocol hygiene

Use the exact operation key **`op`**, with optional **`target`** for the host-allowed serial. Do not add undocumented request fields such as `action`, `device`, `artifact`, `avd`, or arbitrary emulator options.

The queue is untrusted. Apply defense-in-depth when operating on paths, text fields, emulator names, APK files or logged output. Fixing a vulnerability should include a regression test that does not need live ADB.

## Real emulator tests

Only test on operator-approved, disposable emulators with synthetic data. Do not send real SMS/MMS, log into real accounts, delete app data or use destructive UI actions during routine CI or PR verification. Avoid modifying an active production-like user service from an untrusted sandbox.

## Issue reports and security disclosures

Regular bug reports should include Python/ADB/Android versions, sanitized request and response JSON, reproduction steps, and expected vs actual behavior. Use [SECURITY.md](SECURITY.md) for private security reporting; never post exploit details publicly.

Contributions are made under the repository's [Apache License 2.0](LICENSE).
