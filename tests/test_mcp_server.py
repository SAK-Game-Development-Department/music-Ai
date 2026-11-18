import contextlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from musicai import mcp_server, tools
from musicai.schema import validate_against

ROOT = Path(__file__).resolve().parent.parent


def rpc(id_, method, params=None):
    m = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        m["params"] = params
    return m


class HandleTest(unittest.TestCase):
    def test_initialize_and_notification(self):
        r = mcp_server.handle(rpc(1, "initialize", {"protocolVersion": "2024-11-05"}))
        self.assertEqual(r["result"]["protocolVersion"], "2024-11-05")
        self.assertIn("tools", r["result"]["capabilities"])
        self.assertEqual(mcp_server.handle(rpc(1, "initialize", {"protocolVersion": "1999"}))["result"]["protocolVersion"],
                         mcp_server.SUPPORTED_PROTOCOLS[1])
        self.assertIsNone(mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(mcp_server.handle(rpc(2, "ping"))["result"], {})

    def test_tools_list(self):
        r = mcp_server.handle(rpc(3, "tools/list"))["result"]["tools"]
        self.assertEqual([t["name"] for t in r], ["compose", "kaeuta", "validate", "export", "make_song"])
        for t in r:
            self.assertTrue(t["description"])
            self.assertEqual(t["inputSchema"]["type"], "object")
            validate_against({}, t["inputSchema"])  # 自前の検証器が解釈できるスキーマであること
            json.dumps(t)

    def test_call_success_and_tool_failure(self):
        r = mcp_server.handle(rpc(4, "tools/call", {"name": "validate", "arguments": {"name": "hoshi", "check": True}}))
        res = r["result"]
        self.assertFalse(res["isError"])
        self.assertTrue(json.loads(res["content"][0]["text"])["ok"])
        r = mcp_server.handle(rpc(5, "tools/call", {"name": "export", "arguments": {"name": "none"}}))["result"]
        self.assertTrue(r["isError"])
        self.assertIn("見つかりません", r["content"][0]["text"])
        r = mcp_server.handle(rpc(6, "tools/call", {"name": "export", "arguments": {}}))["result"]
        self.assertTrue(r["isError"])
        self.assertIn("name", r["content"][0]["text"])

    def test_unexpected_exception_is_reported(self):
        with mock.patch.dict(tools.TOOLS["validate"], {"run": mock.Mock(side_effect=RuntimeError("boom"))}), \
                mock.patch("traceback.print_exc"):
            r = mcp_server.handle(rpc(7, "tools/call", {"name": "validate", "arguments": {"name": "hoshi"}}))["result"]
        self.assertTrue(r["isError"])
        self.assertIn("内部エラー", r["content"][0]["text"])

    def test_protocol_errors(self):
        self.assertEqual(mcp_server.handle(rpc(8, "resources/list"))["error"]["code"], mcp_server.METHOD_NOT_FOUND)
        self.assertEqual(mcp_server.handle(rpc(9, "tools/call", {}))["error"]["code"], mcp_server.INVALID_PARAMS)
        self.assertEqual(mcp_server.handle(rpc(9, "tools/list", []))["error"]["code"], mcp_server.INVALID_PARAMS)
        self.assertEqual(mcp_server.handle([1])["error"]["code"], mcp_server.INVALID_REQUEST)
        self.assertEqual(mcp_server.handle({"jsonrpc": "1.0", "id": 1, "method": "x"})["error"]["code"],
                         mcp_server.INVALID_REQUEST)


class ServeTest(unittest.TestCase):
    def run_serve(self, lines):
        out = io.StringIO()
        mcp_server.serve(io.StringIO("\n".join(lines) + "\n"), out)
        return [json.loads(x) for x in out.getvalue().splitlines()]

    def test_lines_and_parse_error(self):
        replies = self.run_serve([json.dumps(rpc(1, "ping")), "", "{not json", json.dumps({"jsonrpc": "2.0", "method": "x"}),
                                  json.dumps(rpc(2, "ping"))])
        self.assertEqual([r.get("id") for r in replies], [1, None, 2])  # 通知には返信しない
        self.assertEqual(replies[1]["error"]["code"], mcp_server.PARSE_ERROR)

    def test_tool_print_does_not_corrupt_stdout(self):
        def noisy(_args):
            print("これはプロトコルに混ぜてはいけない")
            return {"ok": True}
        with mock.patch.dict(tools.TOOLS["validate"], {"run": noisy}), contextlib.redirect_stderr(io.StringIO()) as err:
            replies = self.run_serve([json.dumps(rpc(1, "tools/call", {"name": "validate", "arguments": {}}))])
        self.assertEqual(len(replies), 1)
        self.assertFalse(replies[0]["result"]["isError"])
        self.assertIn("プロトコルに混ぜてはいけない", err.getvalue())  # 標準エラーへ回っている


class SubprocessTest(unittest.TestCase):
    def test_real_server_round_trip(self):
        msgs = [rpc(1, "initialize", {"protocolVersion": "2025-06-18"}),
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                rpc(2, "tools/list"),
                rpc(3, "tools/call", {"name": "validate", "arguments": {"yaml": "title: x\n"}})]
        p = subprocess.run([sys.executable, "-m", "musicai", "mcp"], cwd=ROOT, capture_output=True, text=True,
                           input="\n".join(json.dumps(m) for m in msgs) + "\n", timeout=60)
        replies = [json.loads(x) for x in p.stdout.splitlines()]  # 標準出力は JSON だけ
        self.assertEqual([r["id"] for r in replies], [1, 2, 3])
        self.assertEqual(len(replies[1]["result"]["tools"]), 5)
        self.assertFalse(json.loads(replies[2]["result"]["content"][0]["text"])["ok"])


if __name__ == "__main__":
    unittest.main()
