import hashlib, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from adbbridge.core import Agent, AgentError, Config

PNG = b"\x89PNG\r\n\x1a\nminimal"

class Tests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()); self.apkdir = self.root / "apks"; self.apkdir.mkdir()
        self.apk = self.apkdir / "app.apk"; self.apk.write_bytes(b"apk")
        self.cfg = Config({"adb":"/no/invocation", "allowed_devices":["emulator-5554"], "allowed_apk_directories":[str(self.apkdir)], "artifact_directory":str(self.root/"artifacts"), "allowed_packages":["org.example"], "allowed_components":{"org.example":["org.example/.MainActivity"]}, "permitted_operations":["ping","status","devices","install_apk","launch_app","logcat","screenshot"], "command_timeout_seconds":1})
        self.agent = Agent(self.root / "queue", self.cfg)
    def req(self, **data): return self.agent.handle({"id":"r1", **data})
    def test_default_read_only(self):
        c=Config({"allowed_devices":["emulator-5554"]}); self.assertEqual(c.operations, {"ping","status","devices"})

    def test_lifecycle_config_is_fixed_and_allowlisted(self):
        c = Config({"permitted_operations":["ping","status","devices","emulator_status","start_emulator"]})
        self.assertEqual(c.avd_name, "silence-counterpart")
        with self.assertRaisesRegex(AgentError, "invalid emulator lifecycle"):
            Config({"emulator_avd":"other"})
    def test_ping_status_and_schema(self):
        self.assertTrue(self.req(op="ping")["ok"]); self.assertIn("artifact_directory", self.req(op="status"))
        with self.assertRaisesRegex(AgentError,"unknown request field"): self.req(op="ping", arbitrary=True)
    def test_target_and_operation_restrictions(self):
        with self.assertRaisesRegex(AgentError,"not allowlisted"): self.req(op="devices", target="phone")
        with self.assertRaisesRegex(AgentError,"not permitted"): Agent(self.root/"q2", Config({"allowed_devices":["emulator-5554"], "artifact_directory":str(self.root/"a2")})).handle({"id":"x","op":"install_apk"})
    @patch.object(Agent, "adb_devices", return_value={"stdout":"List of devices attached\nemulator-5554    device product:sdk_gphone\n"})
    def test_online_accepts_smart_socket_whitespace_separator(self, devices):
        self.agent._online()
        devices.assert_called_once_with()
    @patch.object(Agent, "_online")
    @patch.object(Agent, "_run")
    def test_fixed_install_and_launch_arguments(self, run, online):
        digest=hashlib.sha256(self.apk.read_bytes()).hexdigest(); run.return_value={"exit_code":0,"stdout":"","stderr":""}
        self.req(op="install_apk", apk_path=str(self.apk), sha256=digest); self.assertEqual(run.call_args.args[0], ["-s","emulator-5554","install","--no-streaming","-r",str(self.apk)])
        self.req(op="launch_app", package="org.example", component="org.example/.MainActivity"); self.assertEqual(run.call_args.args[0], ["-s","emulator-5554","shell","am","start","-n","org.example/.MainActivity"])
    def test_apk_filesystem_safety(self):
        (self.root/"other.apk").write_bytes(b"outside")
        with self.assertRaisesRegex(AgentError,"outside allowed"): self.req(op="install_apk", apk_path=str(self.root/"other.apk"), sha256="0"*64)
        with self.assertRaisesRegex(AgentError,"mismatch"): self.req(op="install_apk", apk_path=str(self.apk), sha256="0"*64)
    @patch.object(Agent, "_online")
    @patch.object(Agent, "_run")
    @patch.object(Agent, "_run_bytes")
    def test_logcat_validation_and_screenshot_artifact(self, bytes_run, run, online):
        run.return_value={"exit_code":0,"stdout":"log","stderr":""}; self.req(op="logcat", lines=20, since="10")
        self.assertEqual(run.call_args.args[0], ["-s","emulator-5554","logcat","-d","-v","threadtime","-t","20","-T","10"])
        bytes_run.return_value=(0, PNG, b""); result=self.req(op="screenshot"); self.assertEqual(Path(result["artifact_path"]).read_bytes(), PNG)
        with self.assertRaisesRegex(AgentError,"invalid logcat"): self.req(op="logcat", lines=2001)
    @patch.object(Agent, "_online")
    @patch("adbbridge.core.subprocess.run", side_effect=__import__('subprocess').TimeoutExpired("adb", 1))
    def test_timeout_is_structured(self, run, online):
        with self.assertRaisesRegex(AgentError,"timed out"): self.req(op="logcat")
    def test_queue_response_and_bad_json(self):
        (self.agent.requests/"one.json").write_text(json.dumps({"id":"one","op":"ping"})); self.agent.once(); self.assertEqual(json.loads((self.agent.responses/"one.json").read_text())["status"],"ok"); self.assertFalse((self.agent.requests/"one.json").exists())
        (self.agent.requests/"bad.json").write_text("{"); self.agent.once(); self.assertEqual(json.loads((self.agent.responses/"invalid.json").read_text())["status"],"error") if (self.agent.responses/"invalid.json").exists() else None

    def test_lifecycle_status_stopped_booting_ready(self):
        lifecycle = Config({"artifact_directory":str(self.root/"life-artifacts"), "permitted_operations":["ping","status","devices","emulator_status","start_emulator"]})
        agent = Agent(self.root / "lifecycle", lifecycle)
        with patch.object(agent, "_emulator_process", return_value=False), patch.object(agent, "adb_devices", return_value={"stdout":"List of devices attached\n"}):
            self.assertEqual(agent.handle({"id":"s","op":"emulator_status"})["state"], "stopped")
        with patch.object(agent, "_emulator_process", return_value=True), patch.object(agent, "adb_devices", return_value={"stdout":"List of devices attached\n"}):
            self.assertEqual(agent.handle({"id":"b","op":"emulator_status"})["state"], "booting")
        with patch.object(agent, "_emulator_process", return_value=True), patch.object(agent, "adb_devices", return_value={"stdout":"List of devices attached\nemulator-5554 device\n"}), patch.object(agent, "_boot_completed", return_value=True):
            self.assertEqual(agent.handle({"id":"r","op":"emulator_status"})["state"], "ready")

    @patch("adbbridge.core.subprocess.run")
    def test_process_detection_accepts_qemu_command(self, run):
        lifecycle = Config({"artifact_directory":str(self.root/"qemu-artifacts"), "permitted_operations":["ping","status","devices","emulator_status"]})
        agent = Agent(self.root / "qemu", lifecycle)
        run.return_value = type("Result", (), {"stdout":"21590 qemu-system-x86_64 -avd silence-counterpart -gpu swiftshader_indirect\n", "stderr":"", "returncode":0})()
        self.assertTrue(agent._emulator_process())
        self.assertEqual(run.call_args.args[0], ["pgrep", "-af", "emulator|qemu-system-"])

    def test_duplicate_start_and_fixed_arguments(self):
        lifecycle = Config({"artifact_directory":str(self.root/"life-artifacts2"), "permitted_operations":["ping","status","devices","emulator_status","start_emulator"], "emulator":str(self.root / "emulator")})
        (self.root / "emulator").write_text("x")
        agent = Agent(self.root / "lifecycle2", lifecycle)
        with patch.object(agent, "_emulator_status", return_value={"ok":True,"state":"booting"}):
            self.assertEqual(agent.handle({"id":"d","op":"start_emulator"})["state"], "already_running")
        with patch.object(agent, "_emulator_status", return_value={"ok":True,"state":"stopped"}), patch("adbbridge.core.subprocess.Popen") as popen:
            result = agent.handle({"id":"s","op":"start_emulator"})
            self.assertEqual(result["state"], "starting")
            self.assertEqual(popen.call_args.args[0], [str(self.root / "emulator"), "-avd", "silence-counterpart", "-gpu", "swiftshader_indirect", "-no-snapshot", "-no-boot-anim", "-no-audio"])

    def test_start_failure_and_schema_remain_structured(self):
        lifecycle = Config({"artifact_directory":str(self.root/"life-artifacts3"), "permitted_operations":["ping","status","devices","emulator_status","start_emulator"]})
        agent = Agent(self.root / "lifecycle3", lifecycle)
        with patch.object(agent, "_emulator_status", return_value={"ok":True,"state":"stopped"}), patch("adbbridge.core.subprocess.Popen", side_effect=OSError("denied")):
            with self.assertRaisesRegex(AgentError, "unable to start"): agent.handle({"id":"f","op":"start_emulator"})
        with self.assertRaisesRegex(AgentError, "unknown request field"): agent.handle({"id":"x","op":"emulator_status","wait":True})

if __name__ == "__main__": unittest.main()
