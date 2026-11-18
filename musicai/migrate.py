"""曲・仕様ファイルのバージョン移行。

形式を変えるたびに CURRENT_VERSION を上げ、MIGRATIONS に「旧→新」の変換関数を足す。
変換関数は YAML のテキストを受け取りテキストを返す（コメントを消さないため）。
"""
from __future__ import annotations

from pathlib import Path

import yaml

CURRENT_VERSION = 1


def _v0_to_v1(text: str) -> str:
    """schema_version が無いファイルに 1 を付ける。先頭のコメント行・空行の後ろに入れる。"""
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1
    nl = "\r\n" if text.count("\r\n") else "\n"
    lines.insert(i, f"schema_version: 1{nl}")
    return "".join(lines)


MIGRATIONS = {0: _v0_to_v1}


def file_version(text: str) -> int:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("YAML のトップがマップではありません")
    v = data.get("schema_version", 0)
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise ValueError(f"schema_version が整数ではありません: {v!r}")
    return v


def migrate_text(text: str) -> tuple[str, int, int]:
    """(新しいテキスト, 元のバージョン, 新しいバージョン)。"""
    start = ver = file_version(text)
    if ver > CURRENT_VERSION:
        raise ValueError(f"schema_version {ver} はこのツールより新しい形式です（対応は {CURRENT_VERSION} まで）")
    while ver < CURRENT_VERSION:
        text = MIGRATIONS[ver](text)
        ver = file_version(text)
    return text, start, ver


def migrate_file(path: str | Path, dry_run: bool = False) -> tuple[int, int]:
    p = Path(path)
    # newline="" で改行コードをそのまま保つ
    with open(p, encoding="utf-8", newline="") as f:
        text = f.read()
    new, a, b = migrate_text(text)
    if new != text and not dry_run:
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(new)
    return a, b


def ensure_version(data: dict) -> dict:
    """辞書に schema_version が無ければ現在の値を足す（画面・API の入口用）。"""
    if "schema_version" in data:
        return data
    return {"schema_version": CURRENT_VERSION, **data}
