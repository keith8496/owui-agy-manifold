"""Protocol-level checks for the fake ACP peer used by integration tests."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

FAKE = Path(__file__).with_name("fake_acp.py")


class FakeACPTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.log = Path(self.temp.name) / "requests.jsonl"

    def start(self, scenario="stream"):
        env = dict(os.environ, FAKE_ACP_SCENARIO=scenario, FAKE_ACP_LOG=str(self.log))
        proc = subprocess.Popen([sys.executable, "-u", str(FAKE)], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, text=True, env=env)
        def cleanup():
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=3)
        self.addCleanup(cleanup)
        return proc

    def send(self, proc, message):
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    def read(self, proc):
        return json.loads(proc.stdout.readline())

    def request(self, proc, ident, method, params=None):
        self.send(proc, {"jsonrpc": "2.0", "id": ident, "method": method,
                         "params": params or {}})

    def test_stream_chunks_and_completion(self):
        proc = self.start()
        self.request(proc, 1, "initialize")
        self.assertEqual(self.read(proc)["result"]["protocolVersion"], 1)
        self.request(proc, 2, "session/new")
        self.assertEqual(self.read(proc)["result"]["sessionId"], "fake-session")
        self.request(proc, 3, "session/prompt")
        chunks = [self.read(proc), self.read(proc)]
        self.assertEqual("".join(c["params"]["update"]["content"]["text"] for c in chunks), "hello world")
        self.assertEqual(self.read(proc)["result"]["stopReason"], "end_turn")

    def test_model_error(self):
        proc = self.start("model_error")
        self.request(proc, 1, "session/set_model")
        self.assertEqual(self.read(proc)["error"]["code"], -32602)

    def test_permission_roundtrip(self):
        proc = self.start("permission")
        self.request(proc, 1, "session/prompt")
        permission = self.read(proc)
        self.assertEqual(permission["method"], "session/request_permission")
        self.send(proc, {"jsonrpc": "2.0", "id": permission["id"],
                         "result": {"outcome": {"outcome": "cancelled"}}})
        self.assertEqual(self.read(proc)["result"]["stopReason"], "end_turn")
        records = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(records[-1]["result"]["outcome"]["outcome"], "cancelled")

    def test_timeout_peer_can_be_killed_and_reaped(self):
        proc = self.start("timeout")
        self.request(proc, 1, "session/prompt")
        with self.assertRaises(subprocess.TimeoutExpired):
            proc.wait(timeout=0.1)
        proc.kill()
        self.assertIsNotNone(proc.wait(timeout=3))


if __name__ == "__main__":
    unittest.main()
