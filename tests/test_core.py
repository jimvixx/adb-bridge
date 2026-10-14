import json, socket, tempfile, threading, time, unittest
from pathlib import Path
from adbbridge.core import Agent, Config

def agent_for(port=5037):
    return Agent(Path(tempfile.mkdtemp())/'q', Config({'adb':'/path/that-must-not-be-invoked','allowed_devices':['emulator-5554'],'command_timeout_seconds':1,'host':'127.0.0.1','port':port}))

def fake_server(response, port=0, hold=False):
    ready=threading.Event(); box=[]
    def run():
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(('127.0.0.1',port)); s.listen(1); box.append(s.getsockname()[1]); ready.set()
            c,_=s.accept()
            with c:
                if hold: time.sleep(2); return
                header=c.recv(4); c.recv(int(header,16)); c.sendall(response)
    t=threading.Thread(target=run,daemon=True); t.start(); ready.wait(); return box[0]

class Tests(unittest.TestCase):
  def test_service_uses_installed_cli_and_separate_queue(self):
    service=(Path(__file__).parents[1]/'systemd'/'adbbridge.service').read_text(); self.assertIn('/.local/share/adbbridge/venv/bin/adbbridge',service); self.assertNotIn('/Repos/adb-bridge',service); self.assertIn('.gradle/adbbridge-queue',service); self.assertIn('.config/adbbridge/config.json',service)
  def request(self,agent,rid,op):
    (agent.requests/f'{rid}.json').write_text(json.dumps({'id':rid,'op':op})); agent.once(); return json.loads((agent.responses/f'{rid}.json').read_text())
  def test_ping_status_devices_and_allowlist(self):
    payload=b'emulator-5554          device product:sdk\nphone\tunauthorized\n'; port=fake_server(b'OKAY'+f'{len(payload):04x}'.encode()+payload); a=agent_for(port)
    self.assertEqual(self.request(a,'a','ping')['status'],'ok'); self.assertEqual(self.request(a,'b','status')['status'],'ok'); r=self.request(a,'c','devices'); self.assertIn('emulator-5554',r['result']['stdout']); self.assertNotIn('phone',r['result']['stdout'])
  def test_tab_entries_and_exact_serial_matching(self):
    payload=b'emulator-5554\tdevice\nemulator-55540 device\n'; port=fake_server(b'OKAY'+f'{len(payload):04x}'.encode()+payload); r=self.request(agent_for(port),'exact','devices'); self.assertIn('emulator-5554\tdevice',r['result']['stdout']); self.assertNotIn('emulator-55540',r['result']['stdout'])
  def test_empty_and_malformed_lines_are_ignored(self):
    payload=b'\nmalformed\n   \n\temulator-5554\n'; port=fake_server(b'OKAY'+f'{len(payload):04x}'.encode()+payload); r=self.request(agent_for(port),'malformed','devices'); self.assertEqual(r['result']['stdout'],'List of devices attached\n')
  def test_server_unavailable(self):
    r=self.request(agent_for(1),'u','devices'); self.assertEqual(r['error']['code'],'server_unavailable')
  def test_protocol_fail_and_timeout(self):
    payload=b'nope'; r=self.request(agent_for(fake_server(b'FAIL'+f'{len(payload):04x}'.encode()+payload)),'f','devices'); self.assertEqual(r['error']['code'],'server_protocol_error'); r=self.request(agent_for(fake_server(b'',hold=True)),'t','devices'); self.assertEqual(r['error']['code'],'server_unavailable')
  def test_mutation_and_target_rejected(self):
    a=agent_for(); self.assertEqual(self.request(a,'m','install')['status'],'error'); (a.requests/'x.json').write_text(json.dumps({'id':'x','op':'status','target':'physical'})); a.once(); self.assertEqual(json.loads((a.responses/'x.json').read_text())['status'],'error')
