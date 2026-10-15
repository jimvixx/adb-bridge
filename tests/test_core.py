import hashlib, json, subprocess, tempfile, unittest
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
        c = Config({"allowed_devices":["emulator-5554"], "emulator_avd":"Pixel_API_35", "permitted_operations":["ping","status","devices","emulator_status","start_emulator"]})
        self.assertEqual(c.avd_name, "Pixel_API_35")
        with self.assertRaisesRegex(AgentError, "invalid emulator AVD"):
            Config({"allowed_devices":["emulator-5554"], "emulator_avd":"bad;command"})
    def test_ping_status_and_schema(self):
        self.assertTrue(self.req(op="ping")["ok"]); self.assertIn("artifact_directory", self.req(op="status"))
        with self.assertRaisesRegex(AgentError,"unknown request field"): self.req(op="ping", arbitrary=True)
    @patch.object(Agent, "_online")
    @patch.object(Agent, "_run", return_value={"exit_code": 0, "stdout": "", "stderr": ""})
    def test_ui_fixed_argv(self, run, online):
        ui = Config({"allowed_devices":["emulator-5554"], "artifact_directory":str(self.root/"ui"), "permitted_operations":["ping","status","devices","tap","swipe","keyevent","input_text"]})
        agent = Agent(self.root / "uiq", ui)
        agent.handle({"id":"t","op":"tap","x":10,"y":20})
        self.assertEqual(run.call_args.args[0], ["-s","emulator-5554","shell","input","tap","10","20"])
        agent.handle({"id":"s","op":"swipe","x1":1,"y1":2,"x2":3,"y2":4,"duration_ms":50})
        self.assertEqual(run.call_args.args[0], ["-s","emulator-5554","shell","input","swipe","1","2","3","4","50"])
        agent.handle({"id":"k","op":"keyevent","keyevent":"BACK"})
        self.assertEqual(run.call_args.args[0], ["-s","emulator-5554","shell","input","keyevent","BACK"])
        agent.handle({"id":"i","op":"input_text","text":"Test 123!"})
        self.assertEqual(run.call_args.args[0], ["-s","emulator-5554","shell","input","text","Test 123!"])
    @patch.object(Agent, "_online")
    @patch("adbbridge.core.subprocess.run")
    def test_every_ui_operation_uses_allowlisted_device_and_shell_false(self, run, online):
        run.return_value = type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        ui = Config({"allowed_devices":["emulator-5554"], "artifact_directory":str(self.root/"ui-device"), "permitted_operations":["ping","status","devices","tap","swipe","keyevent","input_text"]})
        agent = Agent(self.root / "ui-device-q", ui)
        requests = [
            {"id":"t","op":"tap","x":1,"y":2},
            {"id":"s","op":"swipe","x1":1,"y1":2,"x2":3,"y2":4},
            {"id":"k","op":"keyevent","keyevent":"ENTER"},
            {"id":"i","op":"input_text","text":"hello world"},
        ]
        for request in requests:
            agent.handle(request)
            argv = run.call_args.args[0]
            self.assertEqual(argv[1:3], ["-s", "emulator-5554"])
            self.assertIs(run.call_args.kwargs["shell"], False)
        for target in ("phone", "emulator-5556", "127.0.0.1:5555"):
            with self.assertRaisesRegex(AgentError, "not allowlisted"):
                agent.handle({**requests[0], "id":"bad", "target":target})
        with self.assertRaisesRegex(AgentError, "unknown request field"):
            agent.handle({**requests[0], "id":"bad-field", "adb_args":["-s", "phone"]})
    @patch.object(Agent, "_online")
    @patch("adbbridge.core.subprocess.run")
    def test_input_text_rejects_remote_shell_metacharacters_before_execution(self, run, online):
        ui = Config({"allowed_devices":["emulator-5554"], "artifact_directory":str(self.root/"ui-text"), "permitted_operations":["ping","status","devices","input_text"]})
        agent = Agent(self.root / "ui-text-q", ui)
        for text in ("a;b", "$(id)", "`id`", "a|b", "a&b", "a'b", 'a"b', "a\nb", "100%", "a\\b", "a/b", "a(b)", "a=b"):
            with self.subTest(text=text), self.assertRaisesRegex(AgentError, "unsupported characters"):
                agent.handle({"id":"unsafe", "op":"input_text", "text":text})
        run.assert_not_called()
        agent.handle({"id":"safe", "op":"input_text", "text":"Hello, test 123!"})
        run.assert_called_once_with([ui.adb, "-s", "emulator-5554", "shell", "input", "text", "Hello, test 123!"], text=True, capture_output=True, timeout=ui.timeout, shell=False, check=False)
    def test_ui_disabled_and_validation(self):
        with self.assertRaisesRegex(AgentError, "not permitted"): self.req(op="tap", x=1, y=1)
        ui = Config({"allowed_devices":["emulator-5554"], "artifact_directory":str(self.root/"ui2"), "permitted_operations":["ping","status","devices","tap","swipe","keyevent","input_text"]})
        agent = Agent(self.root / "uiq2", ui)
        for request in ({"id":"x","op":"tap","x":-1,"y":1}, {"id":"x","op":"tap","x":1080,"y":1}, {"id":"x","op":"swipe","x1":1,"y1":1,"x2":2,"y2":2,"duration_ms":0}, {"id":"x","op":"keyevent","keyevent":"POWER"}, {"id":"x","op":"input_text","text":"a; rm -rf /"}, {"id":"x","op":"input_text","text":"a"*121}, {"id":"x","op":"tap","x":1,"y":1,"text":"extra"}):
            with self.assertRaises(AgentError): agent.handle(request)
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
        lifecycle = Config({"allowed_devices":["emulator-5554"], "artifact_directory":str(self.root/"life-artifacts"), "emulator_avd":"silence-counterpart", "permitted_operations":["ping","status","devices","emulator_status","start_emulator"]})
        agent = Agent(self.root / "lifecycle", lifecycle)
        with patch.object(agent, "_emulator_process", return_value=False), patch.object(agent, "adb_devices", return_value={"stdout":"List of devices attached\n"}):
            self.assertEqual(agent.handle({"id":"s","op":"emulator_status"})["state"], "stopped")
        with patch.object(agent, "_emulator_process", return_value=True), patch.object(agent, "adb_devices", return_value={"stdout":"List of devices attached\n"}):
            self.assertEqual(agent.handle({"id":"b","op":"emulator_status"})["state"], "booting")
        with patch.object(agent, "_emulator_process", return_value=True), patch.object(agent, "adb_devices", return_value={"stdout":"List of devices attached\nemulator-5554 device\n"}), patch.object(agent, "_boot_completed", return_value=True):
            self.assertEqual(agent.handle({"id":"r","op":"emulator_status"})["state"], "ready")
    @patch("adbbridge.core.subprocess.run")
    def test_process_detection_accepts_qemu_command(self, run):
        lifecycle = Config({"allowed_devices":["emulator-5554"], "artifact_directory":str(self.root/"qemu-artifacts"), "emulator_avd":"silence-counterpart", "permitted_operations":["ping","status","devices","emulator_status"]})
        agent = Agent(self.root / "qemu", lifecycle)
        run.return_value = type("Result", (), {"stdout":"21590 qemu-system-x86_64 -avd silence-counterpart -gpu swiftshader_indirect\n", "stderr":"", "returncode":0})()
        self.assertTrue(agent._emulator_process())
        self.assertEqual(run.call_args.args[0], ["pgrep", "-af", "emulator|qemu-system-"])
    def test_duplicate_start_and_fixed_arguments(self):
        lifecycle = Config({"allowed_devices":["emulator-5554"], "artifact_directory":str(self.root/"life-artifacts2"), "emulator_avd":"silence-counterpart", "permitted_operations":["ping","status","devices","emulator_status","start_emulator"], "emulator":str(self.root / "emulator")})
        (self.root / "emulator").write_text("x")
        agent = Agent(self.root / "lifecycle2", lifecycle)
        with patch.object(agent, "_emulator_status", return_value={"ok":True,"state":"booting"}):
            self.assertEqual(agent.handle({"id":"d","op":"start_emulator"})["state"], "already_running")
        with patch.object(agent, "_emulator_status", return_value={"ok":True,"state":"stopped"}), patch("adbbridge.core.subprocess.Popen") as popen:
            result = agent.handle({"id":"s","op":"start_emulator"})
            self.assertEqual(result["state"], "starting")
            self.assertEqual(popen.call_args.args[0], [str(self.root / "emulator"), "-avd", "silence-counterpart", "-gpu", "swiftshader_indirect", "-no-snapshot", "-no-boot-anim", "-no-audio"])
    def test_start_failure_and_schema_remain_structured(self):
        emulator = self.root / "emulator"
        emulator.write_text("x")
        emulator.chmod(0o700)
        lifecycle = Config({"allowed_devices":["emulator-5554"], "artifact_directory":str(self.root/"life-artifacts3"), "emulator_avd":"silence-counterpart", "permitted_operations":["ping","status","devices","emulator_status","start_emulator"], "emulator":str(emulator)})
        agent = Agent(self.root / "lifecycle3", lifecycle)
        with patch.object(agent, "_emulator_status", return_value={"ok":True,"state":"stopped"}), patch("adbbridge.core.subprocess.Popen", side_effect=OSError("denied")):
            with self.assertRaisesRegex(AgentError, "unable to start"): agent.handle({"id":"f","op":"start_emulator"})
        with self.assertRaisesRegex(AgentError, "unknown request field"): agent.handle({"id":"x","op":"emulator_status","wait":True})


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = Config({
            "allowed_devices": ["emulator-5556"],
            "emulator_avd": "Pixel_API_35",
            "artifact_directory": str(self.root / "artifacts"),
            "allowed_packages": ["com.example.notes"],
            "allowed_components": {"com.example.notes": ["com.example.notes/.MainActivity"]},
            "permitted_operations": [
                "ping", "status", "devices", "emulator_status", "start_emulator",
                "launch_app", "tap", "swipe", "keyevent", "input_text",
            ],
        })
        self.agent = Agent(self.root / "queue", self.config)

    def test_only_one_emulator_serial_is_allowed(self):
        for devices in ([], ["device-123"], ["127.0.0.1:5555"],
                        ["emulator-5554", "emulator-5556"], "emulator-5554", None):
            with self.subTest(devices=devices), self.assertRaisesRegex(AgentError, "exactly one emulator"):
                Config({"allowed_devices": devices})
        with self.assertRaisesRegex(AgentError, "exactly one emulator"):
            Config({})
        self.assertEqual(self.config.serial, "emulator-5556")

    def test_other_avd_is_valid_but_shell_like_names_are_not(self):
        self.assertEqual(self.config.avd_name, "Pixel_API_35")
        for name in ("a;reboot", "my avd", "../x", "a/b", "$(id)", ""):
            with self.subTest(name=name), self.assertRaisesRegex(AgentError, "invalid emulator AVD"):
                Config({"allowed_devices": ["emulator-5556"], "emulator_avd": name})
        with self.assertRaisesRegex(AgentError, "emulator_avd is required"):
            Config({"allowed_devices": ["emulator-5556"], "permitted_operations": ["ping", "status", "devices", "start_emulator"]})

    def test_read_only_config_needs_no_avd(self):
        cfg = Config({"allowed_devices": ["emulator-5560"]})
        self.assertIsNone(cfg.avd_name)
        self.assertEqual(cfg.operations, {"ping", "status", "devices"})

    def test_target_defaults_to_configured_serial_and_rejects_other(self):
        self.agent.validate({"id": "x", "op": "tap", "x": 4, "y": 9})
        self.agent.validate({"id": "x", "op": "tap", "target": "emulator-5556", "x": 4, "y": 9})
        for target in ("emulator-5554", "R58N1234567", "emulator-55560"):
            with self.subTest(target=target), self.assertRaisesRegex(AgentError, "not allowlisted"):
                self.agent.validate({"id": "x", "op": "tap", "target": target, "x": 4, "y": 9})

    def test_ui_and_launcher_use_selected_serial(self):
        with patch.object(self.agent, "_online"), patch.object(self.agent, "_run", return_value={"exit_code": 0, "stdout": "", "stderr": ""}) as run:
            self.agent.handle({"id": "tap", "op": "tap", "x": 12, "y": 24})
            self.assertEqual(run.call_args.args[0][:2], ["-s", "emulator-5556"])
            self.agent.handle({"id": "launch", "op": "launch_app", "package": "com.example.notes", "component": "com.example.notes/.MainActivity"})
            self.assertEqual(run.call_args.args[0], ["-s", "emulator-5556", "shell", "am", "start", "-n", "com.example.notes/.MainActivity"])

    def test_discovery_filters_other_devices(self):
        # Exercise existing Smart Socket result filtering with a mocked socket payload.
        payload = b"emulator-5554 device product:x\nemulator-5556    device product:y\nR58N123 device product:z\n"
        framed = b"OKAY" + f"{len(payload):04x}".encode() + payload
        class FakeSocket:
            def __init__(self, value): self.value = value
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def sendall(self, _: bytes): pass
            def recv(self, size):
                chunk, self.value = self.value[:size], self.value[size:]
                return chunk
        with patch("adbbridge.core.socket.create_connection", return_value=FakeSocket(framed)):
            result = self.agent.adb_devices()
        self.assertIn("emulator-5556", result["stdout"])
        self.assertNotIn("emulator-5554", result["stdout"])
        self.assertNotIn("R58N123", result["stdout"])

    def test_process_detection_uses_configured_avd(self):
        fake = type("Result", (), {"stdout": "111 qemu-system-x86_64 -avd Other_AVD\n222 qemu-system-x86_64 -avd Pixel_API_35 -gpu software\n"})()
        with patch("adbbridge.core.subprocess.run", return_value=fake):
            self.assertTrue(self.agent._emulator_process())
        fake.stdout = "111 qemu-system-x86_64 -avd Other_AVD\n"
        with patch("adbbridge.core.subprocess.run", return_value=fake):
            self.assertFalse(self.agent._emulator_process())


if __name__ == "__main__": unittest.main()
