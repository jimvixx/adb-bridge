# Security model
ADBBridge treats the queue as untrusted. The host executable and JSON security configuration must be host-owned and not writable by the sandbox; the AI gets queue write access only. Queue files are validated, operations are allowlisted, responses are atomic, and no shell or arbitrary ADB arguments are accepted.

Milestone 0 implements only `ping`, `status`, and read-only `devices`. Mutations are rejected. There is no ADB-server restart, listener, APK installation, shell command, or physical-device access policy. Future approval data from the same untrusted queue must never be sufficient authorization.
