"""プロンプトテンプレートのスキーマ通過率を測る。

AI の出力（YAML）を集めたファイル／フォルダを渡すと、`validate` に合格した割合を出す。
AI を呼び出す処理は含まない。測り方は docs/04_プロンプトの使い方と測定.md を参照。

    python scripts/measure_prompts.py outputs/compose/            # specs 用の出力を測る
    python scripts/measure_prompts.py outputs/revise/ --kind song --threshold 0.9

入力に使えるファイル:
  *.yaml / *.yml   そのまま検証する
  *.md / *.txt     AI の返答そのまま。最初の ```yaml コードブロックを取り出して検証する
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from musicai.schema import detect_kind, validate_data  # noqa: E402

FENCE = re.compile(r"```(?:ya?ml)[^\n]*\n(.*?)```", re.DOTALL | re.IGNORECASE)
YAML_EXT = {".yaml", ".yml"}
TEXT_EXT = {".md", ".txt"}


@dataclass
class Item:
    path: Path
    ok: bool
    errors: list[tuple[str, str]] = field(default_factory=list)


def extract_yaml(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in YAML_EXT:
        return text
    m = FENCE.search(text)
    if not m:
        raise ValueError("```yaml のコードブロックが見つかりません")
    return m.group(1)


def collect(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for x in paths:
        p = Path(x)
        if p.is_dir():
            out += sorted(f for f in p.iterdir() if f.suffix.lower() in YAML_EXT | TEXT_EXT)
        elif p.exists():
            out.append(p)
        else:
            raise FileNotFoundError(x)
    return out


def measure(paths: list[str], kind: str | None = None) -> list[Item]:
    items = []
    for f in collect(paths):
        try:
            data = yaml.safe_load(extract_yaml(f))
        except ValueError as e:
            items.append(Item(f, False, [("(extract)", str(e))]))
            continue
        except yaml.YAMLError as e:
            items.append(Item(f, False, [("(yaml)", f"YAML として読めません: {e}")]))
            continue
        r = validate_data(data, kind or detect_kind(f, data))
        items.append(Item(f, r.ok, r.errors))
    return items


def rate(items: list[Item]) -> float:
    return sum(i.ok for i in items) / len(items) if items else 0.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AI 出力 YAML のスキーマ通過率を測る")
    ap.add_argument("path", nargs="+", help="YAML / Markdown のファイル、またはフォルダ")
    ap.add_argument("--kind", choices=["song", "spec"], help="省略時は specs/ 配下か中身で判断")
    ap.add_argument("--threshold", type=float, default=0.9, help="目標の通過率（既定 0.9）。下回ると終了コード 1")
    a = ap.parse_args(argv)
    try:
        items = measure(a.path, a.kind)
    except FileNotFoundError as e:
        print(f"エラー: 見つかりません: {e}", file=sys.stderr)
        return 2
    if not items:
        print("エラー: 測る対象のファイルがありません", file=sys.stderr)
        return 2
    for i in items:
        print(f"{'OK' if i.ok else 'NG'}  {i.path}")
        for p, m in i.errors:
            print(f"      {p}: {m}")
    r = rate(items)
    n_ok = sum(i.ok for i in items)
    print(f"\nスキーマ通過率: {n_ok}/{len(items)} = {r:.0%}（目標 {a.threshold:.0%}）→ {'達成' if r >= a.threshold else '未達'}")
    return 0 if r >= a.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
