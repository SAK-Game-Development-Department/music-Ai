"""AI・CLI・MCP から呼べる操作（compose / kaeuta / validate / export）。

どれも「辞書の入力 → 辞書の出力」の Python 関数。MCP サーバ（mcp_server.py）と CLI は、ここを呼ぶだけ。

守っていること:
- 書き込むのは songs/・output/ の中だけ。曲は名前（songs/<name>.yaml）で指定し、任意のパスは受け取らない
- 書き出す前に必ず validate（ファイル構造）→ check（警告ゼロ）を通す。通らなければ書き出さない
- 既存の曲は、overwrite: true を付けない限り上書きしない
- 失敗は ToolError（日本語の理由つき）。入力のスキーマに合わない呼び出しは、呼ぶ前に弾く
"""
from __future__ import annotations

from pathlib import Path

import yaml

from . import service
from .migrate import ensure_version
from .schema import validate_against, validate_data, validate_file

EXPORT_FORMATS = ["midi", "musicxml", "lyrics", "wav", "mp3"]
_AUDIO = {"wav", "mp3"}
_EXT = {"midi": ".mid", "musicxml": ".musicxml", "lyrics": "_歌詞.txt", "wav": ".wav", "mp3": ".mp3"}


class ToolError(ValueError):
    """利用者（AI を含む）に返してよい、日本語のエラー。"""


def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(service.DATA_DIR.resolve()).as_posix()
    except ValueError:
        return p.name


def _song_file(name: str) -> Path:
    p = service.SONGS_DIR / f"{service.safe_name(name)}.yaml"
    if not p.is_file():
        raise ToolError(f"曲が見つかりません: {name}")
    return p


def _errors(result) -> list[dict]:
    return [{"path": p, "message": m} for p, m in result.errors]


def _ensure_free(name: str, overwrite: bool) -> None:
    p = service.SONGS_DIR / f"{service.safe_name(name)}.yaml"
    if p.exists() and not overwrite:
        raise ToolError(f"「{p.stem}」はすでにあります。上書きするなら overwrite を true に（先にアプリで「バージョンを保存」しておくと戻せます）")


def _warnings(song) -> list[str]:
    return [w for s in song.sections.values() for w in s.warnings]


# ---------------------------------------------------------------- compose
def compose_data(args: dict) -> tuple[str, dict]:
    """作曲仕様 → (保存名, 曲の辞書)。何も保存しない。"""
    from .composer import compose as compose_spec

    if ("spec" in args) == ("spec_name" in args):
        raise ToolError("spec（仕様そのもの）か spec_name（specs/ にあるファイル名）のどちらか 1 つを指定してください")
    if "spec_name" in args:
        p = service.SPECS_DIR / f"{service.safe_name(args['spec_name'])}.yaml"
        if not p.is_file():
            raise ToolError(f"作曲仕様が見つかりません: {args['spec_name']}")
        spec = yaml.safe_load(p.read_text(encoding="utf-8"))
    else:
        spec = args["spec"]
    if not isinstance(spec, dict):
        raise ToolError("作曲仕様はマップ（YAML のキーと値）で書いてください")
    spec = ensure_version(spec)
    r = validate_data(spec, "spec")
    if not r.ok:
        raise ToolError("作曲仕様の形式が正しくありません:\n" + r.format())
    data = compose_spec(spec)
    return args.get("name") or data.get("title") or "untitled", data


def compose(args: dict) -> dict:
    from .song import check_report, song_from_dict

    name, data = compose_data(args)
    _ensure_free(name, bool(args.get("overwrite")))
    song = song_from_dict(data)  # 楽曲として読めるか（読めなければここで ValueError）
    path = service.save_song_text(name, service.dump_yaml(data))
    return {"name": path.stem, "path": _rel(path), "warnings": _warnings(song), "report": check_report(song)}


# ---------------------------------------------------------------- kaeuta
def kaeuta_data(args: dict) -> tuple[str, dict, list[str]]:
    """保存済みの曲 + 新しい歌詞 → (保存名, 曲の辞書, 調整レポート)。何も保存しない。"""
    src = _song_file(args["song"])
    lyrics = args["lyrics"]
    if not lyrics:
        raise ToolError("lyrics に、セクション名: 新しい歌詞 を 1 つ以上入れてください")
    data = yaml.safe_load(src.read_text(encoding="utf-8"))
    try:
        new, report = service.kaeuta(data, lyrics, args.get("title"))
    except ValueError as e:
        raise ToolError(str(e)) from None
    return args.get("name") or f"{src.stem}_kaeuta", new, report


def kaeuta(args: dict) -> dict:
    from .song import song_from_dict

    name, new, report = kaeuta_data(args)
    _ensure_free(name, bool(args.get("overwrite")))
    song = song_from_dict(new)
    path = service.save_song_text(name, service.dump_yaml(new))
    return {"name": path.stem, "path": _rel(path), "report": report, "warnings": _warnings(song)}


# ---------------------------------------------------------------- validate
def validate(args: dict) -> dict:
    """ファイル構造の検証。check: true なら、合格した曲について楽曲ルールの警告も返す。"""
    kind = args.get("kind")
    if ("name" in args) == ("yaml" in args):
        raise ToolError("name（保存済みの曲・仕様）か yaml（YAML のテキスト）のどちらか 1 つを指定してください")
    if "name" in args:
        kind = kind or "song"
        d = service.SONGS_DIR if kind == "song" else service.SPECS_DIR
        p = d / f"{service.safe_name(args['name'])}.yaml"
        if not p.is_file():
            raise ToolError(f"見つかりません: {kind} {args['name']}")
        result = validate_file(p, kind)
        text = None if not result.ok else p.read_text(encoding="utf-8")
    else:
        kind = kind or "song"
        try:
            data = yaml.safe_load(args["yaml"])
        except yaml.YAMLError:
            return {"ok": False, "kind": kind, "errors": [{"path": "(yaml)", "message": "YAML として読めません"}]}
        result = validate_data(data, kind)
        text = args["yaml"] if result.ok else None
    out = {"ok": result.ok, "kind": kind, "errors": _errors(result)}
    if args.get("check") and result.ok and kind == "song":
        from .song import song_from_dict

        try:
            out["warnings"] = _warnings(song_from_dict(yaml.safe_load(text)))
        except ValueError as e:
            out["ok"] = False
            out["errors"].append({"path": "(song)", "message": str(e)})
    return out


# ---------------------------------------------------------------- export
def export_song_file(path: Path, stem: str, out_dir: Path, formats: list[str], allow_warnings: bool = False) -> dict:
    """曲ファイルを書き出す。validate → check を通らなければ書き出さない。"""
    from .song import load_song

    r = validate_file(path, "song")
    if not r.ok:
        raise ToolError("曲ファイルの形式が正しくありません（先に validate を通してください）:\n" + r.format())
    try:
        song = load_song(path)
    except ValueError as e:
        raise ToolError(str(e)) from None
    warns = _warnings(song)
    if warns and not allow_warnings:
        raise ToolError("警告があるため書き出しません（check を警告ゼロにしてください）:\n" + "\n".join("  " + w for w in warns))
    audio = bool(_AUDIO & set(formats))
    made = service.render_song(song, stem, audio=audio, out_dir=out_dir)
    key = {"midi": "midi", "musicxml": "musicxml", "lyrics": "lyrics", "wav": "wav", "mp3": "mp3"}
    files = {f: made[key[f]] for f in formats if key[f] in made}
    missing = [f for f in formats if f not in files]
    return {"files": files, "missing": missing, "warnings": warns}


def export(args: dict) -> dict:
    formats = list(dict.fromkeys(args.get("formats") or ["midi", "musicxml", "lyrics"]))
    p = _song_file(args["name"])
    res = export_song_file(p, p.stem, service.OUTPUT_DIR, formats, bool(args.get("allow_warnings")))
    res["files"] = {f: _rel(service.OUTPUT_DIR / name) for f, name in res["files"].items()}
    if res["missing"]:
        res["note"] = "作れなかった形式: " + ", ".join(res["missing"]) + "（mp3 は ffmpeg が必要です）"
    return res


def make_song(args: dict) -> dict:
    """生成 → 検証 → 書き出しを一括で行う（失敗したら songs/ と output/ は変わらない）。詳しくは pipeline.py。"""
    from . import pipeline

    return pipeline.run(args)


# ---------------------------------------------------------------- 登録（MCP の tools/list が使う）
_NAME = {"type": "string", "description": "曲の名前（songs/<名前>.yaml の「名前」の部分）"}

TOOLS: dict[str, dict] = {
    "compose": {
        "description": "作曲仕様（歌詞・コード進行・構成）からメロディ付きの曲を作って songs/ に保存する。"
                       "仕様は schemas/spec.schema.json の形（spec か、specs/ のファイル名 spec_name のどちらか）。",
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "spec": {"type": "object", "description": "作曲仕様そのもの（schema_version は省略可）"},
                "spec_name": {"type": "string", "description": "specs/<名前>.yaml の名前"},
                "name": {"type": "string", "description": "保存する曲の名前（省略時はタイトル）"},
                "overwrite": {"type": "boolean", "description": "同名の曲を上書きする（既定 false）"},
            },
        },
        "run": compose,
    },
    "kaeuta": {
        "description": "保存済みの曲の歌詞を差し替え、メロディを自動調整した替え歌を songs/ に保存する。",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["song", "lyrics"],
            "properties": {
                "song": {**_NAME, "description": "元の曲の名前"},
                "lyrics": {"type": "object", "additionalProperties": {"type": "string"},
                           "description": "セクション名: 新しい歌詞。漢字は {漢字|よみ}、フレーズは / か改行で区切る"},
                "title": {"type": "string", "description": "替え歌のタイトル"},
                "name": {"type": "string", "description": "保存名（省略時は <元の名前>_kaeuta）"},
                "overwrite": {"type": "boolean", "description": "同名の曲を上書きする（既定 false）"},
            },
        },
        "run": kaeuta,
    },
    "validate": {
        "description": "曲・作曲仕様のファイル構造をスキーマで検証する。合格なら ok: true。不合格なら errors に"
                       "キーのパスと理由が入る。check: true で、曲の楽曲ルールの警告（音符数とモーラ数など）も返す。",
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "name": {"type": "string", "description": "保存済みのファイルの名前（kind が song なら songs/、spec なら specs/）"},
                "yaml": {"type": "string", "description": "保存前の YAML テキスト"},
                "kind": {"enum": ["song", "spec"], "description": "song（既定）か spec"},
                "check": {"type": "boolean", "description": "曲の警告も返す（既定 false）"},
            },
        },
        "run": validate,
    },
    "export": {
        "description": "保存済みの曲を output/ に書き出す。既定は midi・musicxml・lyrics（すぐ終わる）。"
                       "wav・mp3 は音を作るので時間がかかる。validate と check（警告ゼロ）を通らない曲は書き出さない。",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["name"],
            "properties": {
                "name": _NAME,
                "formats": {"type": "array", "items": {"enum": EXPORT_FORMATS},
                            "description": "書き出す形式。既定は midi・musicxml・lyrics"},
                "allow_warnings": {"type": "boolean", "description": "check の警告があっても書き出す（既定 false）"},
            },
        },
        "run": export,
    },
    "make_song": {
        "description": "作曲（mode=compose）または替え歌（mode=kaeuta）から、validate → check（警告ゼロ）→ 書き出しまでを"
                       "1 回で行う。途中で失敗したら songs/ と output/ は変わらない（反映の途中の失敗は元に戻す）。"
                       "compose は spec か spec_name、kaeuta は song と lyrics を渡す。",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "required": ["mode"],
            "properties": {
                "mode": {"enum": ["compose", "kaeuta"], "description": "compose（作曲）か kaeuta（替え歌）"},
                "spec": {"type": "object", "description": "[compose] 作曲仕様そのもの"},
                "spec_name": {"type": "string", "description": "[compose] specs/<名前>.yaml の名前"},
                "song": {"type": "string", "description": "[kaeuta] 元の曲の名前"},
                "lyrics": {"type": "object", "additionalProperties": {"type": "string"},
                           "description": "[kaeuta] セクション名: 新しい歌詞"},
                "title": {"type": "string", "description": "[kaeuta] 替え歌のタイトル"},
                "name": {"type": "string", "description": "保存する曲の名前（省略時は、作曲はタイトル、替え歌は <元の名前>_kaeuta）"},
                "formats": {"type": "array", "items": {"enum": EXPORT_FORMATS},
                            "description": "書き出す形式。既定は midi・musicxml・lyrics。wav・mp3 は時間がかかる"},
                "allow_warnings": {"type": "boolean", "description": "check の警告があっても進める（既定 false）"},
                "overwrite": {"type": "boolean", "description": "同名の曲を上書きする（既定 false）。上書き前の内容は自動でバージョンに残る"},
            },
        },
        "run": make_song,
    },
}


def call(name: str, args: dict | None) -> dict:
    """入力を検査してからツールを実行する。入力が不正なら ToolError。"""
    tool = TOOLS.get(name)
    if tool is None:
        raise ToolError(f"そのツールはありません: {name}（使えるのは {', '.join(TOOLS)}）")
    args = {} if args is None else args
    r = validate_against(args, tool["inputSchema"])
    if not r.ok:
        raise ToolError("入力が正しくありません:\n" + r.format())
    return tool["run"](args)
