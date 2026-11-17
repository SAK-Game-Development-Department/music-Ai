"""コマンドライン: python -m musicai <command> ...

  render   曲ファイル → WAV / MP3 / MIDI / MusicXML / 歌詞カード
  check    曲ファイルの検証（小節の長さ、音符数と歌詞モーラ数）
  compose  作曲仕様（歌詞・進行・構成）→ メロディ付きの曲ファイル
  kaeuta   既存の曲の歌詞を差し替え、メロディを自動調整した替え歌ファイルを作る
  mora     歌詞のモーラ分割を表示
  progressions  定番コード進行の一覧
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

import yaml


def cmd_render(a):
    from .arrange import arrange
    from .export import lyric_sheet, write_midi, write_musicxml
    from .song import check_report, load_song
    from .synth import render, wav_to_mp3, write_wav

    song = load_song(a.song)
    print(check_report(song))
    out = Path(a.out or "output")
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(a.song).stem
    if a.tempo:
        song.tempo = a.tempo
    arr = arrange(song)
    write_midi(song, arr, out / f"{stem}.mid")
    write_musicxml(song, out / f"{stem}.musicxml")
    (out / f"{stem}_歌詞.txt").write_text(lyric_sheet(song), encoding="utf-8")
    files = [f"{stem}.mid", f"{stem}.musicxml", f"{stem}_歌詞.txt"]
    if not a.no_audio:
        mute = set(a.mute.split(",")) if a.mute else None
        audio = render(arr, song.tempo, mute)
        wav = out / f"{stem}.wav"
        write_wav(audio, wav)
        files.append(wav.name)
        if wav_to_mp3(wav, out / f"{stem}.mp3"):
            files.append(f"{stem}.mp3")
    print(f"\n出力 → {out}/: " + ", ".join(files))


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
    from .kaeuta import fit_lyrics
    from .song import check_report, load_song, melody_to_text, parse_melody, save_song_dict, _resolve_spec

    data = yaml.safe_load(Path(a.song).read_text(encoding="utf-8"))
    song = load_song(a.song)
    if a.lyrics_file:
        new_lyrics = yaml.safe_load(Path(a.lyrics_file).read_text(encoding="utf-8"))
        if not isinstance(new_lyrics, dict):
            sys.exit("歌詞ファイルは「セクション名: 歌詞」の形式で書いてください")
    elif a.section and a.lyrics is not None:
        new_lyrics = {a.section: a.lyrics}
    else:
        sys.exit("--section と --lyrics、または --lyrics-file を指定してください")

    new = copy.deepcopy(data)
    new["title"] = a.title or f"{data.get('title', '')}（替え歌）"
    for sec_name, text in new_lyrics.items():
        if sec_name not in data.get("sections", {}):
            sys.exit(f"セクション {sec_name!r} がありません（ある: {', '.join(data['sections'])}）")
        spec = _resolve_spec(sec_name, data["sections"])
        notes, _ = parse_melody(spec.get("melody", ""), song.beats_per_bar)
        fitted, report = fit_lyrics(notes, text)
        print(f"【{sec_name}】")
        print("\n".join("  " + r for r in report))
        sec = dict(new["sections"][sec_name] or {})
        sec.pop("base", None)
        sec.pop("fit", None)
        merged = {**spec, **sec}
        merged.pop("fit", None)
        merged["melody"] = melody_to_text(fitted, song.beats_per_bar, song.key.prefer_flat)
        merged["lyrics"] = text
        new["sections"][sec_name] = merged
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

    mo = sp.add_parser("mora", help="歌詞のモーラを数える")
    mo.add_argument("text")
    mo.set_defaults(func=cmd_mora)

    pr = sp.add_parser("progressions", help="定番コード進行の一覧")
    pr.add_argument("--key", default="C major")
    pr.set_defaults(func=cmd_progressions)

    a = p.parse_args(argv)
    try:
        a.func(a)
    except ValueError as e:
        sys.exit(f"エラー: {e}")


if __name__ == "__main__":
    main()
