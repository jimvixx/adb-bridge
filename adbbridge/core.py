"""Security-sensitive queue worker; keep the public operation set explicit."""
from __future__ import annotations
import json, os, re, socket, tempfile, time
from pathlib import Path
ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
READ_OPS = {"ping", "status", "devices"}
DISABLED_OPS = {"install", "start_app", "logcat", "screenshot", "input", "test_hook"}
class AgentError(Exception):
    def __init__(self, message, code="agent_error"):
        super().__init__(message); self.code = code
class Config:
    def __init__(self, data):
        if not isinstance(data, dict): raise AgentError("configuration must be an object")
        self.adb = str(data.get("adb", Path.home() / "Android/Sdk/platform-tools/adb"))
        self.host = str(data.get("host", "127.0.0.1"))
        self.port = int(data.get("port", 5037))
        if self.host != "127.0.0.1" or not 1 <= self.port <= 65535: raise AgentError("ADB server endpoint must be 127.0.0.1:1..65535")
        self.devices = data.get("allowed_devices")
        if not isinstance(self.devices, list) or not self.devices or any(not isinstance(x, str) or not x for x in self.devices): raise AgentError("allowed_devices must be a non-empty list")
        self.timeout = int(data.get("command_timeout_seconds", 15))
        if not 1 <= self.timeout <= 60: raise AgentError("command timeout must be 1..60 seconds")
        self.max_response_bytes = int(data.get("max_response_bytes", 1_048_576))
        if not 1024 <= self.max_response_bytes <= 16_777_216: raise AgentError("max response must be 1024..16777216 bytes")
def load_config(path: Path) -> Config: return Config(json.loads(path.read_text(encoding="utf-8")))
class Agent:
    def __init__(self, queue: Path, config: Config):
        self.queue, self.config = queue, config; self.requests, self.responses = queue/"requests", queue/"responses"
        self.requests.mkdir(parents=True, exist_ok=True); self.responses.mkdir(parents=True, exist_ok=True)
        for p in (queue, self.requests, self.responses): os.chmod(p, 0o700)
    def validate(self, req):
        if not isinstance(req, dict) or not isinstance(req.get("id"), str) or not ID_RE.fullmatch(req["id"]): raise AgentError("invalid request id")
        op = req.get("op")
        if op not in READ_OPS | DISABLED_OPS: raise AgentError("operation not allowed")
        if req.get("target") is not None and req["target"] not in self.config.devices: raise AgentError("target is not allowlisted")
        return op
    def _read_exact(self, sock, size):
        data = bytearray()
        while len(data) < size:
            chunk = sock.recv(min(65536, size - len(data)))
            if not chunk: raise AgentError("ADB server closed the connection", "server_protocol_error")
            data.extend(chunk)
        return bytes(data)
    def adb_devices(self):
        # Direct Smart Socket access: this never invokes adb and therefore cannot auto-start adbd.
        try:
            with socket.create_connection((self.config.host, self.config.port), timeout=self.config.timeout) as sock:
                command = b"host:devices-l"; sock.sendall(f"{len(command):04x}".encode() + command)
                status = self._read_exact(sock, 4)
                if status == b"FAIL":
                    length = int(self._read_exact(sock, 4), 16)
                    if length > self.config.max_response_bytes: raise AgentError("ADB failure response too large", "server_protocol_error")
                    raise AgentError(self._read_exact(sock, length).decode("utf-8", "replace"), "server_protocol_error")
                if status != b"OKAY": raise AgentError("invalid ADB server status", "server_protocol_error")
                length = int(self._read_exact(sock, 4), 16)
                if length > self.config.max_response_bytes: raise AgentError("ADB response too large", "server_protocol_error")
                payload = self._read_exact(sock, length).decode("utf-8", "replace")
        except AgentError: raise
        except (OSError, socket.timeout) as e: raise AgentError(f"ADB server unavailable: {e}", "server_unavailable")
        visible = []
        for line in payload.splitlines():
            fields = line.split(maxsplit=1)
            if len(fields) >= 2 and fields[0] in self.config.devices:
                visible.append(line)
        return {"exit_code": 0, "stdout": "List of devices attached\n" + ("\n".join(visible) + "\n" if visible else ""), "stderr": "", "allowed_devices": self.config.devices}
    def handle(self, req):
        op = self.validate(req)
        if op == "ping": return {"ok": True, "agent": "adbbridge", "version": 1}
        if op == "status": return {"ok": True, "adb": self.config.adb, "allowed_devices": self.config.devices, "queue": str(self.queue), "mutations": "disabled"}
        if op == "devices":
            result = self.adb_devices(); result["ok"] = result["exit_code"] == 0; return result
        raise AgentError("operation recognized but disabled; mutation approval is not implemented")
    def write_response(self, rid, payload):
        out = self.responses/f"{rid}.json"; fd, tmp = tempfile.mkstemp(prefix=f".{rid}.", dir=self.responses)
        with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(payload, f, ensure_ascii=False, sort_keys=True); f.write("\n"); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, out); os.chmod(out, 0o600)
    def process_file(self, path):
        try:
            req = json.loads(path.read_text(encoding="utf-8")); rid = req.get("id", "invalid") if isinstance(req, dict) else "invalid"
            try: response = {"id": rid, "status": "ok", "result": self.handle(req)}
            except AgentError as e: response = {"id": rid, "status": "error", "error": {"code": e.code, "message": str(e)}}
            except Exception as e: response = {"id": rid, "status": "error", "error": {"code": "agent_error", "message": str(e)}}
            if isinstance(rid, str) and ID_RE.fullmatch(rid): self.write_response(rid, response)
        finally: path.unlink(missing_ok=True)
    def once(self):
        for p in sorted(self.requests.glob("*.json")): self.process_file(p)
    def loop(self, interval=.25):
        while True: self.once(); time.sleep(interval)
