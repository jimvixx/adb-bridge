"""Fail-closed JSON queue worker for one explicitly allowlisted emulator."""
from __future__ import annotations
import hashlib, json, os, re, socket, subprocess, tempfile, time
from pathlib import Path
ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
PACKAGE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z][a-zA-Z0-9_]*)+$")
COMPONENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*\/(?:\.)?[A-Za-z][A-Za-z0-9_.$]*$")
EMULATOR_SERIAL_RE = re.compile(r"^emulator-[0-9]{4,5}$")
AVD_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
READ_OPS = {"ping", "status", "devices", "emulator_status"}
MUTATION_OPS = {"install_apk", "launch_app", "logcat", "screenshot", "start_emulator", "tap", "swipe", "keyevent", "input_text"}
UI_OPS = {"tap", "swipe", "keyevent", "input_text"}
KEYEVENTS = {"BACK", "HOME", "ENTER", "DEL"}
REQUIRED_OPS = {"ping", "status", "devices"}
class AgentError(Exception):
    def __init__(self, message, code="agent_error"):
        super().__init__(message); self.code = code
class Config:
    def __init__(self, data):
        if not isinstance(data, dict): raise AgentError("configuration must be an object", "config_invalid")
        self.adb = str(data.get("adb", Path.home() / "Android/Sdk/platform-tools/adb"))
        self.host, self.port = str(data.get("host", "127.0.0.1")), int(data.get("port", 5037))
        if self.host != "127.0.0.1" or not 1 <= self.port <= 65535: raise AgentError("ADB server endpoint must be 127.0.0.1:1..65535", "config_invalid")
        self.devices = data.get("allowed_devices")
        if not isinstance(self.devices, list) or len(self.devices) != 1 or not isinstance(self.devices[0], str) or not EMULATOR_SERIAL_RE.fullmatch(self.devices[0]): raise AgentError("allowed_devices must contain exactly one emulator serial", "config_invalid")
        self.serial = self.devices[0]
        self.timeout = int(data.get("command_timeout_seconds", 15)); self.max_response_bytes = int(data.get("max_response_bytes", 1_048_576))
        self.max_apk_bytes = int(data.get("max_apk_bytes", 200 * 1024 * 1024)); self.max_screenshot_bytes = int(data.get("max_screenshot_bytes", 16 * 1024 * 1024))
        if not 1 <= self.timeout <= 60 or not 1024 <= self.max_response_bytes <= 16_777_216: raise AgentError("invalid limits", "config_invalid")
        self.apk_dirs = [Path(x).resolve() for x in data.get("allowed_apk_directories", [])]
        self.artifact_dir = Path(data.get("artifact_directory", Path.home() / ".gradle/adbbridge-artifacts")).resolve()
        self.packages, self.components = data.get("allowed_packages", []), data.get("allowed_components", {})
        self.emulator_path = Path(data.get("emulator", Path.home() / "Android/Sdk/emulator/emulator")).resolve()
        self.avd_name = data.get("emulator_avd")
        self.boot_timeout = int(data.get("emulator_boot_timeout_seconds", 45))
        self.emulator_env = {k: str(data[k]) for k in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR") if k in data}
        if not self.emulator_path.is_absolute() or not 1 <= self.boot_timeout <= 300: raise AgentError("invalid emulator lifecycle configuration", "config_invalid")
        if self.avd_name is not None and (not isinstance(self.avd_name, str) or not AVD_NAME_RE.fullmatch(self.avd_name)): raise AgentError("invalid emulator AVD name", "config_invalid")
        if any(k not in {"DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR"} for k in self.emulator_env): raise AgentError("invalid emulator environment", "config_invalid")
        self.operations = set(data.get("permitted_operations", sorted(REQUIRED_OPS)))
        if not self.operations <= READ_OPS | MUTATION_OPS or not REQUIRED_OPS <= self.operations: raise AgentError("invalid permitted operations", "config_invalid")
        if {"emulator_status", "start_emulator"} & self.operations and self.avd_name is None: raise AgentError("emulator_avd is required for emulator lifecycle operations", "config_invalid")
        if any(not isinstance(x, str) or not PACKAGE_RE.fullmatch(x) for x in self.packages): raise AgentError("invalid allowed package", "config_invalid")
        if not isinstance(self.components, dict) or any(p not in self.packages or not isinstance(v, list) or any(not isinstance(c, str) or not COMPONENT_RE.fullmatch(c) or c.split("/", 1)[0] != p for c in v) for p, v in self.components.items()): raise AgentError("invalid allowed component", "config_invalid")
        self.ui_width = int(data.get("ui_width", 1080)); self.ui_height = int(data.get("ui_height", 1920)); self.max_input_text = int(data.get("max_input_text", 120))
        if not 1 <= self.ui_width <= 10000 or not 1 <= self.ui_height <= 10000 or not 1 <= self.max_input_text <= 1000: raise AgentError("invalid UI limits", "config_invalid")
def load_config(path: Path) -> Config: return Config(json.loads(path.read_text(encoding="utf-8")))
class Agent:
    def __init__(self, queue: Path, config: Config):
        self.queue, self.config = queue, config; self.requests, self.responses = queue / "requests", queue / "responses"
        self.requests.mkdir(parents=True, exist_ok=True); self.responses.mkdir(parents=True, exist_ok=True); self.config.artifact_dir.mkdir(parents=True, exist_ok=True)
        for p in (queue, self.requests, self.responses): os.chmod(p, 0o700)
    def validate(self, req):
        if not isinstance(req, dict) or not isinstance(req.get("id"), str) or not ID_RE.fullmatch(req["id"]): raise AgentError("invalid request id", "schema_invalid")
        op = req.get("op")
        if op not in self.config.operations: raise AgentError("operation not permitted", "operation_denied")
        allowed = {"id", "op", "target", "apk_path", "sha256", "package", "component", "lines", "since", "x", "y", "x1", "y1", "x2", "y2", "duration_ms", "keyevent", "text"}
        if set(req) - allowed: raise AgentError("unknown request field", "schema_invalid")
        if req.get("target", self.config.serial) != self.config.serial: raise AgentError("target is not allowlisted", "target_denied")
        fields = {"id", "op", "target"}
        fields |= {"x", "y"} if op == "tap" else {"x1", "y1", "x2", "y2", "duration_ms"} if op == "swipe" else {"keyevent"} if op == "keyevent" else {"text"} if op == "input_text" else set()
        if set(req) - fields and op in UI_OPS: raise AgentError("field is not valid for this operation", "schema_invalid")
        return op
    def _read_exact(self, sock, size):
        data = bytearray()
        while len(data) < size:
            chunk = sock.recv(min(65536, size - len(data)))
            if not chunk: raise AgentError("ADB server closed the connection", "server_protocol_error")
            data.extend(chunk)
        return bytes(data)
    def adb_devices(self):
        try:
            with socket.create_connection((self.config.host, self.config.port), timeout=self.config.timeout) as sock:
                command = b"host:devices-l"; sock.sendall(f"{len(command):04x}".encode() + command); status = self._read_exact(sock, 4)
                if status != b"OKAY": raise AgentError("ADB server rejected devices request", "server_protocol_error")
                length = int(self._read_exact(sock, 4), 16)
                if length > self.config.max_response_bytes: raise AgentError("ADB response too large", "server_protocol_error")
                payload = self._read_exact(sock, length).decode("utf-8", "replace")
        except AgentError: raise
        except (OSError, socket.timeout) as e: raise AgentError(f"ADB server unavailable: {e}", "server_unavailable")
        visible = [line for line in payload.splitlines() if line.split(maxsplit=1)[:1] == [self.config.serial]]
        return {"exit_code": 0, "stdout": "List of devices attached\n" + ("\n".join(visible) + "\n" if visible else ""), "stderr": "", "allowed_devices": self.config.devices}
    def _online(self):
        result = self.adb_devices()
        if not any(line.split()[:2] == [self.config.serial, "device"] for line in result["stdout"].splitlines()): raise AgentError(f"{self.config.serial} is not online", "device_unavailable")
    def _emulator_process(self):
        try:
            result = subprocess.run(["pgrep", "-af", "emulator|qemu-system-"], text=True, capture_output=True, timeout=2, shell=False, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return any(f" -avd {self.config.avd_name}" in line or f" -avd {self.config.avd_name} " in line for line in result.stdout.splitlines())
    def _boot_completed(self):
        result = self._run(["-s", self.config.serial, "shell", "getprop", "sys.boot_completed"], output_limit=128)
        return result["exit_code"] == 0 and result["stdout"].strip() == "1"
    def _emulator_status(self):
        process = self._emulator_process()
        try:
            devices = self.adb_devices()["stdout"]
        except AgentError as e:
            devices = ""
            adb_error = e.code
        else:
            adb_error = None
        adb_state = next((line.split()[1] for line in devices.splitlines() if line.split()[:1] == [self.config.serial] and len(line.split()) > 1), "absent")
        boot = False
        if adb_state == "device":
            try: boot = self._boot_completed()
            except AgentError: pass
        return {"ok": True, "avd": self.config.avd_name, "process": process, "adb_state": adb_state, "boot_completed": boot, "state": "ready" if boot else ("booting" if process or adb_state != "absent" else "stopped"), **({"adb_error": adb_error} if adb_error else {})}
    def _start_emulator(self):
        state = self._emulator_status()
        if state["state"] == "ready": return {**state, "started": False, "state": "already_ready"}
        if state["state"] == "booting": return {**state, "started": False, "state": "already_running"}
        if not self.config.emulator_path.is_file(): raise AgentError("emulator executable is unavailable", "emulator_unavailable")
        env = os.environ.copy(); env.update(self.config.emulator_env)
        try:
            subprocess.Popen([str(self.config.emulator_path), "-avd", self.config.avd_name, "-gpu", "swiftshader_indirect", "-no-snapshot", "-no-boot-anim", "-no-audio"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True, env=env)
        except OSError as e: raise AgentError(f"unable to start emulator: {e}", "emulator_start_failed") from e
        return {"ok": True, "avd": self.config.avd_name, "started": True, "state": "starting", "boot_timeout_seconds": self.config.boot_timeout}
    def _run(self, args, output_limit=None):
        try: result = subprocess.run([self.config.adb, *args], text=True, capture_output=True, timeout=self.config.timeout, shell=False, check=False)
        except subprocess.TimeoutExpired as e: raise AgentError("ADB command timed out", "timeout") from e
        except OSError as e: raise AgentError(f"ADB executable unavailable: {e}", "adb_unavailable") from e
        limit = output_limit or self.config.max_response_bytes
        if len(result.stdout.encode()) > limit or len(result.stderr.encode()) > limit: raise AgentError("ADB output exceeds limit", "output_too_large")
        return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    def _run_bytes(self, args, output_limit):
        try: result = subprocess.run([self.config.adb, *args], capture_output=True, timeout=self.config.timeout, shell=False, check=False)
        except subprocess.TimeoutExpired as e: raise AgentError("ADB command timed out", "timeout") from e
        except OSError as e: raise AgentError(f"ADB executable unavailable: {e}", "adb_unavailable") from e
        if len(result.stdout) > output_limit or len(result.stderr) > output_limit: raise AgentError("ADB output exceeds limit", "output_too_large")
        return result.returncode, result.stdout, result.stderr
    def _coordinate(self, req, name):
        value = req.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0: raise AgentError("coordinates must be non-negative integers", "schema_invalid")
        return value
    def _ui(self, req):
        op = req["op"]
        if op == "tap":
            x, y = self._coordinate(req, "x"), self._coordinate(req, "y")
            if x >= self.config.ui_width or y >= self.config.ui_height: raise AgentError("coordinate is outside display bounds", "schema_invalid")
            args = ["-s", self.config.serial, "shell", "input", "tap", str(x), str(y)]
        elif op == "swipe":
            x1, y1 = self._coordinate(req, "x1"), self._coordinate(req, "y1"); x2, y2 = self._coordinate(req, "x2"), self._coordinate(req, "y2")
            if any(v >= limit for v, limit in ((x1, self.config.ui_width), (x2, self.config.ui_width), (y1, self.config.ui_height), (y2, self.config.ui_height))): raise AgentError("coordinate is outside display bounds", "schema_invalid")
            duration = req.get("duration_ms", 300)
            if not isinstance(duration, int) or isinstance(duration, bool) or not 1 <= duration <= 10000: raise AgentError("invalid swipe duration", "schema_invalid")
            args = ["-s", self.config.serial, "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration)]
        elif op == "keyevent":
            key = req.get("keyevent")
            if not isinstance(key, str) or key not in KEYEVENTS: raise AgentError("keyevent is not allowlisted", "schema_invalid")
            args = ["-s", self.config.serial, "shell", "input", "keyevent", key]
        else:
            value = req.get("text")
            if not isinstance(value, str) or not 1 <= len(value) <= self.config.max_input_text or not re.fullmatch(r"[A-Za-z0-9 .,!?@_+\-]+", value): raise AgentError("text contains unsupported characters or length", "schema_invalid")
            # This conservative alphabet avoids adb input text escaping ambiguity and shell metacharacters.
            args = ["-s", self.config.serial, "shell", "input", "text", value]
        return {"ok": True, **self._run(args)}
    def _apk(self, req):
        raw, digest = req.get("apk_path"), req.get("sha256")
        if not isinstance(raw, str) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest): raise AgentError("invalid APK path or sha256", "schema_invalid")
        path = Path(raw)
        if not path.is_absolute() or path.is_symlink() or not path.is_file(): raise AgentError("APK path is not a regular file", "apk_invalid")
        real = path.resolve()
        if not any(real.is_relative_to(root) for root in self.config.apk_dirs): raise AgentError("APK path is outside allowed directories", "path_denied")
        if real.stat().st_size > self.config.max_apk_bytes: raise AgentError("APK exceeds size limit", "apk_too_large")
        if hashlib.sha256(real.read_bytes()).hexdigest().lower() != digest.lower(): raise AgentError("APK sha256 mismatch", "hash_mismatch")
        return real
    def handle(self, req):
        op = self.validate(req)
        if op == "ping": return {"ok": True, "agent": "adbbridge", "version": 2}
        if op == "status": return {"ok": True, "adb": self.config.adb, "allowed_devices": self.config.devices, "queue": str(self.queue), "artifact_directory": str(self.config.artifact_dir), "permitted_operations": sorted(self.config.operations), "adb_server": "localhost only; Smart Socket discovery is read-only; subprocess ADB may auto-start the configured server"}
        if op == "devices": result = self.adb_devices(); result["ok"] = True; return result
        if op == "emulator_status": return self._emulator_status()
        if op == "start_emulator": return self._start_emulator()
        if op == "install_apk":
            apk = self._apk(req)
            self._online()
            return {"ok": True, **self._run(["-s", self.config.serial, "install", "--no-streaming", "-r", str(apk)])}
        self._online()
        if op in UI_OPS: return self._ui(req)
        if op == "launch_app":
            package, component = req.get("package"), req.get("component")
            if package not in self.config.packages or component not in self.config.components.get(package, []): raise AgentError("package or component is not allowlisted", "component_denied")
            return {"ok": True, **self._run(["-s", self.config.serial, "shell", "am", "start", "-n", component])}
        if op == "logcat":
            lines = req.get("lines", 200)
            if not isinstance(lines, int) or not 1 <= lines <= 2000 or ("since" in req and (not isinstance(req["since"], str) or len(req["since"]) > 40)): raise AgentError("invalid logcat parameters", "schema_invalid")
            args = ["-s", self.config.serial, "logcat", "-d", "-v", "threadtime", "-t", str(lines)]
            if "since" in req: args += ["-T", req["since"]]
            return {"ok": True, **self._run(args)}
        if op == "screenshot":
            out = self.config.artifact_dir / (req["id"] + ".png"); _, data, _ = self._run_bytes(["-s", self.config.serial, "exec-out", "screencap", "-p"], self.config.max_screenshot_bytes)
            if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > self.config.max_screenshot_bytes: raise AgentError("ADB did not return a valid bounded PNG", "artifact_invalid")
            fd, tmp = tempfile.mkstemp(prefix=f".{req['id']}.", suffix=".tmp", dir=self.config.artifact_dir)
            try:
                with os.fdopen(fd, "wb") as f: f.write(data); f.flush(); os.fsync(f.fileno())
                os.replace(tmp, out); os.chmod(out, 0o600)
            finally: Path(tmp).unlink(missing_ok=True)
            return {"ok": True, "artifact_path": str(out), "bytes": len(data)}
        raise AgentError("operation recognized but unavailable", "operation_denied")
    def write_response(self, rid, payload):
        out = self.responses / f"{rid}.json"; fd, tmp = tempfile.mkstemp(prefix=f".{rid}.", dir=self.responses)
        with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(payload, f, ensure_ascii=False, sort_keys=True); f.write("\n"); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, out); os.chmod(out, 0o600)
    def process_file(self, path):
        try:
            try:
                req = json.loads(path.read_text(encoding="utf-8")); rid = req.get("id", "invalid") if isinstance(req, dict) else "invalid"; response = {"id": rid, "status": "ok", "result": self.handle(req)}
            except AgentError as e: response = {"id": locals().get("rid", "invalid"), "status": "error", "error": {"code": e.code, "message": str(e)}}
            except Exception as e: response = {"id": locals().get("rid", "invalid"), "status": "error", "error": {"code": "agent_error", "message": str(e)}}
            if isinstance(response["id"], str) and ID_RE.fullmatch(response["id"]): self.write_response(response["id"], response)
        finally: path.unlink(missing_ok=True)
    def once(self):
        for p in sorted(self.requests.glob("*.json")): self.process_file(p)

    def loop(self, interval=.25):
        while True: self.once(); time.sleep(interval)
