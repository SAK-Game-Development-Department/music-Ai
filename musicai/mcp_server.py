"""MCP サーバ（標準入出力）。AI アプリから musicai の compose / kaeuta / validate / export を呼べる。

    python -m musicai mcp

外部ライブラリは使わず、MCP のうち必要な部分だけを自前で実装している:
  initialize / notifications/initialized / ping / tools/list / tools/call
（リソース・プロンプト・ストリーミングなどには対応しない）。メッセージは 1 行 1 件の JSON-RPC 2.0。
標準出力はプロトコル専用。ログやツール内の print は標準エラーへ回す。
"""
from __future__ import annotations

import contextlib
import json
import sys
import traceback
from typing import IO

from . import tools

SERVER_INFO = {"name": "musicai", "version": "1"}
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


def _error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _result(id_, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def tool_list() -> list[dict]:
    return [{"name": n, "description": t["description"], "inputSchema": t["inputSchema"]} for n, t in tools.TOOLS.items()]


def _call_tool(params: dict) -> dict:
    """ツールの失敗は JSON-RPC のエラーではなく、isError: true の結果で返す（MCP の決まり）。"""
    name, args = params.get("name"), params.get("arguments")
    try:
        with contextlib.redirect_stdout(sys.stderr):  # ツール内の print でプロトコルを壊さない
            out = tools.call(name, args)
        return {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, indent=2)}], "isError": False}
    except ValueError as e:  # ToolError / SongError / LyricError など、利用者に返せる失敗
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    except Exception as e:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        return {"content": [{"type": "text", "text": f"内部エラー: {e}"}], "isError": True}


def handle(msg) -> dict | None:
    """1 件のメッセージを処理して、返信（通知なら None）を返す。"""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _error(msg.get("id") if isinstance(msg, dict) else None, INVALID_REQUEST, "JSON-RPC 2.0 のリクエストではありません")
    method, id_ = msg["method"], msg.get("id")
    params = msg.get("params")
    params = {} if params is None else params
    if "id" not in msg:  # 通知には返信しない（notifications/initialized など）
        return None
    if not isinstance(params, dict):
        return _error(id_, INVALID_PARAMS, "params はオブジェクトにしてください")
    if method == "initialize":
        want = params.get("protocolVersion")
        return _result(id_, {"protocolVersion": want if want in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[1],
                             "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO})
    if method == "ping":
        return _result(id_, {})
    if method == "tools/list":
        return _result(id_, {"tools": tool_list()})
    if method == "tools/call":
        if not isinstance(params.get("name"), str):
            return _error(id_, INVALID_PARAMS, "name（ツール名）が必要です")
        return _result(id_, _call_tool(params))
    return _error(id_, METHOD_NOT_FOUND, f"未対応のメソッドです: {method}")


def serve(stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> None:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = _error(None, PARSE_ERROR, "JSON として読めません")
        else:
            reply = handle(msg)
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()
