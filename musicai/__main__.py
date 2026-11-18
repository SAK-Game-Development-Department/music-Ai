"""コマンドライン: python -m musicai <command> ...

  render   曲ファイル → WAV / MP3 / MIDI / MusicXML / 歌詞カード
  check    曲ファイルの検証（小節の長さ、音符数と歌詞モーラ数）
  compose  作曲仕様（歌詞・進行・構成）→ メロディ付きの曲ファイル
  kaeuta   既存の曲の歌詞を差し替え、メロディを自動調整した替え歌ファイルを作る
  import   YouTube の URL / 音声ファイル → 曲ファイル（テンポ・キー・コード・歌メロを推定、カラオケ音源つき）
  mora     歌詞のモーラ分割を表示
  progressions  定番コード進行の一覧
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


def cmd_check(a):
    from .song import check_report, load_song

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
