"""コマンドライン: python -m musicai <command> ...

  render   曲ファイル → WAV / MP3 / MIDI / MusicXML / 歌詞カード
  validate ファイル構造の検証（schemas/*.schema.json に沿っているか）
  migrate  古い形式のファイルを最新の形式に直す（schema_version を付ける）
  check    曲ファイルの検証（小節の長さ、音符数と歌詞モーラ数）。先に validate を行う
  compose  作曲仕様（歌詞・進行・構成）→ メロディ付きの曲ファイル
  kaeuta   既存の曲の歌詞を差し替え、メロディを自動調整した替え歌ファイルを作る
  import   YouTube の URL / 音声ファイル → 曲ファイル（テンポ・キー・コード・歌メロを推定、カラオケ音源つき）
  mora     歌詞のモーラ分割を表示
  progressions  定番コード進行の一覧
  export   曲ファイル → MIDI / MusicXML / 歌詞カード（既定）。--format で wav / mp3 も。validate と check を通ったものだけ
  pipeline 作曲（または替え歌）→ validate → check → 書き出しを一括で。失敗したら songs/ と output/ は変わらない
  mcp      MCP サーバ（標準入出力）を起動。AI アプリから compose / kaeuta / validate / export を呼べる
  app      アプリ（ブラウザ画面）を起動
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def cmd_render(a):
    from .service import render_song
    from .song import check_report, load_song

    song = load_song(a.song)
    print(check_report(song))
    out = Path(a.out or "output")
    if a.tempo:
        song.tempo = a.tempo
    mute = set(a.mute.split(",")) if a.mute else None
    files = render_song(song, Path(a.song).stem, mute, audio=not a.no_audio, out_dir=out)
    print(f"\n出力 → {out}/: " + ", ".join(files.values()))


def cmd_import(a):
    from .service import import_song

    res = import_song(a.source, a.start or 0, a.end, a.title, progress=lambda m: print("  " + m))
    print("\n".join(res["log"]))
    print(f"\n曲ファイル → songs/{res['name']}.yaml")
    print("次: python -m musicai kaeuta songs/%s.yaml --section パート1 --lyrics \"...\"" % res["name"])


def _expand(paths):
    out = []
    for x in paths:
        p = Path(x)
        out.extend(sorted(p.glob("*.yaml")) if p.is_dir() else [p])
    return out


def cmd_validate(a):
    from .schema import validate_file

    files = _expand(a.path)
    if not files:
        sys.exit("エラー: 対象のファイルがありません")
    bad = 0
    for f in files:
        r = validate_file(f, a.kind)
        if r.ok:
            print(f"OK    {f}")
        else:
            bad += 1
            print(f"NG    {f}\n{r.format()}")
    if bad:
        sys.exit(f"{len(files)} 件中 {bad} 件が不合格です（古い形式なら `python -m musicai migrate` で直せます）")


def cmd_migrate(a):
    from .migrate import migrate_file

    files = _expand(a.path)
    if not files:
        sys.exit("エラー: 対象のファイルがありません")
    bad = 0
    for f in files:  # 1 つ失敗しても残りは続ける
        try:
            before, after = migrate_file(f, a.dry_run)
        except ValueError as e:
            bad += 1
            print(f"失敗    {f}（{e}）")
            continue
        if before == after:
            print(f"変更なし  {f}（バージョン {after}）")
        else:
            print(f"{'移行できます' if a.dry_run else '移行しました'}  {f}（{before} → {after}）")
    if bad:
        sys.exit(f"{len(files)} 件中 {bad} 件を移行できませんでした")


def cmd_export(a):
    from .tools import EXPORT_FORMATS, ToolError, export_song_file

    formats = [f.strip() for f in a.format.split(",") if f.strip()]
    bad = [f for f in formats if f not in EXPORT_FORMATS]
    if bad or not formats:
        sys.exit(f"エラー: --format は {','.join(EXPORT_FORMATS)} から選んでください（{','.join(bad) or '空'}）")
    out = Path(a.out or "output")
    try:
        res = export_song_file(Path(a.song), Path(a.song).stem, out, formats, a.allow_warnings)
    except ToolError as e:
        sys.exit(f"エラー: {e}")
    for f, name in res["files"].items():
        print(f"{f:<9} {out / name}")
    if res["missing"]:
        print("作れなかった形式: " + ", ".join(res["missing"]) + "（mp3 は ffmpeg が必要です）")


def cmd_pipeline(a):
    from .pipeline import run
    from .tools import EXPORT_FORMATS, ToolError

    formats = [f.strip() for f in a.format.split(",") if f.strip()]
    bad = [f for f in formats if f not in EXPORT_FORMATS]
    if bad or not formats:
        sys.exit(f"エラー: --format は {','.join(EXPORT_FORMATS)} から選んでください（{','.join(bad) or '空'}）")
    args = {"mode": a.mode, "formats": formats, "allow_warnings": a.allow_warnings, "overwrite": a.overwrite}
    if a.name:
        args["name"] = a.name
    if a.mode == "compose":
        spec = yaml.safe_load(Path(a.source).read_text(encoding="utf-8")) if Path(a.source).is_file() else None
        if spec is None:
            args["spec_name"] = a.source  # ファイルが無ければ specs/ の名前として扱う
        else:
            args["spec"] = spec
    else:
        if not a.lyrics_file:
            sys.exit("エラー: 替え歌には --lyrics-file（セクション名: 歌詞 の YAML）が必要です")
        args["song"] = a.source
        args["lyrics"] = yaml.safe_load(Path(a.lyrics_file).read_text(encoding="utf-8"))
        if a.title:
            args["title"] = a.title
    try:
        r = run(args)
    except ToolError as e:
        sys.exit(f"エラー: {e}")
    print(" → ".join(r["steps"]))
    print(f"曲: {r['path']}")
    for f, p in r["files"].items():
        print(f"  {f:<9} {p}")
    if r.get("snapshot_version"):
        print(f"（上書き前の内容は、バージョン {r['snapshot_version']} に残しました）")
    if r.get("note"):
        print(r["note"])


def cmd_check(a):
    from .schema import validate_file
    from .song import check_report, load_song

    r = validate_file(a.song, "song")
    if not r.ok:
        sys.exit(f"エラー: ファイルの形式が正しくありません（{a.song}）\n{r.format()}\n"
                 "古い形式なら `python -m musicai migrate` で直せます")
    print(check_report(load_song(a.song)))


def cmd_compose(a):
    from .composer import compose_file
    from .song import check_report, load_song

    out = a.out or str(Path("songs") / (Path(a.spec).stem + ".yaml"))
    compose_file(a.spec, out)
    print(f"作曲しました → {out}")
    print(check_report(load_song(out)))
    print("\n次: python -m musicai render", out)


def cmd_kaeuta(a):
    from .service import kaeuta
    from .song import check_report, load_song, save_song_dict

    data = yaml.safe_load(Path(a.song).read_text(encoding="utf-8"))
    if a.lyrics_file:
        new_lyrics = yaml.safe_load(Path(a.lyrics_file).read_text(encoding="utf-8"))
        if not isinstance(new_lyrics, dict):
            sys.exit("歌詞ファイルは「セクション名: 歌詞」の形式で書いてください")
    elif a.section and a.lyrics is not None:
        new_lyrics = {a.section: a.lyrics}
    else:
        sys.exit("--section と --lyrics、または --lyrics-file を指定してください")
    new, report = kaeuta(data, new_lyrics, a.title)
    print("\n".join(report))
    out = a.out or str(Path(a.song).with_name(Path(a.song).stem + "_kaeuta.yaml"))
    save_song_dict(new, out)
    print(f"\n替え歌ファイル → {out}")
    print(check_report(load_song(out)))
    print("\n次: python -m musicai render", out)


def cmd_mora(a):
    from .lyrics import phrases, split_mora

    syls = split_mora(a.text)
    for i, p in enumerate(phrases(syls)):
        print(f"フレーズ{i + 1} ({sum(1 for s in p if not s.melisma)}モーラ): " + "・".join(s.text for s in p))
    print(f"合計 {sum(1 for s in syls if not s.melisma)} モーラ")


def cmd_progressions(a):
    from .theory import PROGRESSIONS, parse_key, progression_to_chords

    key = parse_key(a.key)
    print(f"キー {key.name()} での定番進行:")
    for name, (deg, desc) in PROGRESSIONS.items():
        print(f"  {name:<20} {deg:<26} → {' '.join(progression_to_chords(name, key)):<28} {desc}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="musicai", description="AI と曲を作る / 替え歌を作るツール")
    sp = p.add_subparsers(dest="cmd", required=True)

    r = sp.add_parser("render", help="曲ファイルを音源・MIDI・楽譜にする")
    r.add_argument("song")
    r.add_argument("-o", "--out", help="出力フォルダ（既定: output）")
    r.add_argument("--tempo", type=float)
    r.add_argument("--mute", help="鳴らさないトラック（例: vocal,drums）カラオケは --mute vocal")
    r.add_argument("--no-audio", action="store_true")
    r.set_defaults(func=cmd_render)

    c = sp.add_parser("check", help="曲ファイルを検証")
    c.add_argument("song")
    c.set_defaults(func=cmd_check)

    v = sp.add_parser("validate", help="ファイル構造の検証（スキーマ）")
    v.add_argument("path", nargs="+", help="YAML ファイル、またはフォルダ")
    v.add_argument("--kind", choices=["song", "spec"], help="省略時は specs/ 配下かどうかなどから判断")
    v.set_defaults(func=cmd_validate)

    mg = sp.add_parser("migrate", help="古い形式のファイルを最新にする")
    mg.add_argument("path", nargs="+", help="YAML ファイル、またはフォルダ")
    mg.add_argument("--dry-run", action="store_true", help="書き換えずに確認だけ")
    mg.set_defaults(func=cmd_migrate)

    ex = sp.add_parser("export", help="MIDI・MusicXML・歌詞カード（と音声）を書き出す")
    ex.add_argument("song")
    ex.add_argument("--format", default="midi,musicxml,lyrics", help="midi,musicxml,lyrics,wav,mp3 のうちカンマ区切り")
    ex.add_argument("-o", "--out", help="出力フォルダ（既定: output）")
    ex.add_argument("--allow-warnings", action="store_true", help="check の警告があっても書き出す")
    ex.set_defaults(func=cmd_export)

    pl = sp.add_parser("pipeline", help="作曲/替え歌 → validate → check → 書き出しを一括で（失敗しても何も変えない）")
    pl.add_argument("mode", choices=["compose", "kaeuta"])
    pl.add_argument("source", help="compose: 作曲仕様のファイル（か specs/ の名前） / kaeuta: 元の曲の名前")
    pl.add_argument("--lyrics-file", help="[kaeuta] YAML: セクション名: 新しい歌詞")
    pl.add_argument("--title", help="[kaeuta] 替え歌のタイトル")
    pl.add_argument("--name", help="保存する曲の名前")
    pl.add_argument("--format", default="midi,musicxml,lyrics", help="midi,musicxml,lyrics,wav,mp3 のうちカンマ区切り")
    pl.add_argument("--allow-warnings", action="store_true")
    pl.add_argument("--overwrite", action="store_true", help="同名の曲を上書き（上書き前の内容は自動でバージョンに残る）")
    pl.set_defaults(func=cmd_pipeline)

    mc = sp.add_parser("mcp", help="MCP サーバ（標準入出力）を起動")
    mc.set_defaults(func=lambda a: __import__("musicai.mcp_server", fromlist=["serve"]).serve())

    m = sp.add_parser("compose", help="作曲仕様からメロディを自動生成")
    m.add_argument("spec")
    m.add_argument("-o", "--out")
    m.set_defaults(func=cmd_compose)

    k = sp.add_parser("kaeuta", help="替え歌を作る")
    k.add_argument("song")
    k.add_argument("--section")
    k.add_argument("--lyrics")
    k.add_argument("--lyrics-file", help="YAML: セクション名: 新しい歌詞")
    k.add_argument("--title")
    k.add_argument("-o", "--out")
    k.set_defaults(func=cmd_kaeuta)

    im = sp.add_parser("import", help="YouTube の URL か音声ファイルから曲を起こす（替え歌用）")
    im.add_argument("source", help="YouTube の URL または音声ファイル")
    im.add_argument("--start", type=float, help="使う範囲の開始（秒）")
    im.add_argument("--end", type=float, help="使う範囲の終了（秒）")
    im.add_argument("--title")
    im.set_defaults(func=cmd_import)

    mo = sp.add_parser("mora", help="歌詞のモーラを数える")
    mo.add_argument("text")
    mo.set_defaults(func=cmd_mora)

    pr = sp.add_parser("progressions", help="定番コード進行の一覧")
    pr.add_argument("--key", default="C major")
    pr.set_defaults(func=cmd_progressions)

    ap = sp.add_parser("app", help="アプリ画面を起動")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.set_defaults(func=lambda a: __import__("musicai.app", fromlist=["run"]).run(a.port, not a.no_browser))

    a = p.parse_args(argv)
    try:
        a.func(a)
    except ValueError as e:
        sys.exit(f"エラー: {e}")


if __name__ == "__main__":
    main()
