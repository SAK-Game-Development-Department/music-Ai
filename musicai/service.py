"""CLI とアプリ（GUI）で共通の処理。"""
from __future__ import annotations

import copy
import re
from fractions import Fraction
from pathlib import Path

import yaml

from .lyrics import phrases, split_mora
from .song import Song, check_report, melody_to_text, parse_melody, save_song_dict, song_from_dict, _resolve_spec

ROOT = Path(__file__).resolve().parent.parent
SONGS_DIR = ROOT / "songs"
SPECS_DIR = ROOT / "specs"
OUTPUT_DIR = ROOT / "output"


def safe_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\s]+', "_", (name or "").strip()).strip("._")
    return name or "untitled"


def dump_yaml(data: dict) -> str:
    class _D(yaml.SafeDumper):
        pass

    def _str(dumper, s):
        if "\n" in s:
            return dumper.represent_scalar("tag:yaml.org,2002:str", s, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", s)

    _D.add_representer(str, _str)
    return yaml.dump(data, Dumper=_D, allow_unicode=True, sort_keys=False, width=1000)


def kaeuta(data: dict, new_lyrics: dict[str, str], title: str | None = None) -> tuple[dict, list[str]]:
    """曲 dict の各セクションの歌詞を差し替え、メロディを合わせた新しい dict と報告を返す。"""
    from .kaeuta import fit_lyrics

    song = song_from_dict(data)
    new = copy.deepcopy(data)
    new["title"] = title or f"{data.get('title', '')}（替え歌）"
    report: list[str] = []
    for sec_name, text in new_lyrics.items():
        if not (text or "").strip():
            continue
        if sec_name not in data.get("sections", {}):
            raise ValueError(f"セクション {sec_name!r} がありません")
        spec = _resolve_spec(sec_name, data["sections"])
        notes, _ = parse_melody(spec.get("melody", ""), song.beats_per_bar)
        if not any(not n.is_rest for n in notes):
            raise ValueError(f"[{sec_name}] にはメロディがないので歌詞を付けられません")
        fitted, rep = fit_lyrics(notes, text)
        report.append(f"【{sec_name}】")
        report.extend("  " + r for r in rep)
        merged = {**spec, **{k: v for k, v in (new["sections"][sec_name] or {}).items() if k not in ("base", "fit")}}
        merged.pop("fit", None)
        merged.pop("base", None)
        merged["melody"] = melody_to_text(fitted, song.beats_per_bar, song.key.prefer_flat)
        merged["lyrics"] = text
        new["sections"][sec_name] = merged
    return new, report


def song_view(song: Song) -> dict:
    """GUI 表示用: セクション・ピアノロール・歌詞情報。"""
    secs = []
    timeline = []
    for start, sec in song.timeline():
        timeline.append({"name": sec.name, "start": float(start), "length": float(sec.length)})
    for name, sec in song.sections.items():
        notes = []
        t = Fraction(0)
        for n in sec.notes:
            if not n.is_rest:
                notes.append({"t": float(t), "d": float(n.dur), "p": n.pitch,
                              "l": n.lyric.text if n.lyric else "", "m": bool(n.lyric and n.lyric.melisma)})
            t += n.dur
        lyr_phr = []
        if sec.lyrics_text:
            try:
                lyr_phr = [[s.text for s in p] for p in phrases(split_mora(sec.lyrics_text))]
            except ValueError:
                pass
        secs.append({
            "name": name,
            "bars": sec.bars,
            "length": float(sec.length),
            "energy": sec.energy,
            "chords": [{"t": float(s), "d": float(d), "name": c} for s, d, c in sec.chords],
            "notes": notes,
            "lyrics": sec.lyrics_text,
            "phrases": lyr_phr,
            "sung": sum(1 for n in sec.notes if not n.is_rest and not n.melisma),
            "has_melody": any(not n.is_rest for n in sec.notes),
        })
    warnings = [w for s in song.sections.values() for w in s.warnings]
    return {
        "title": song.title, "key": song.key.name(), "tempo": song.tempo, "style": song.style,
        "beats_per_bar": song.beats_per_bar, "structure": song.structure, "timeline": timeline,
        "sections": secs, "warnings": warnings, "report": check_report(song),
        "duration_sec": float(song.total_beats) * 60 / song.tempo,
    }


def render_song(song: Song, stem: str, mute: set[str] | None = None, audio: bool = True) -> dict:
    from .arrange import arrange
    from .export import lyric_sheet, write_midi, write_musicxml
    from .synth import render, wav_to_mp3, write_wav

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    arr = arrange(song)
    files = {}
    write_midi(song, arr, OUTPUT_DIR / f"{stem}.mid")
    files["midi"] = f"{stem}.mid"
    write_musicxml(song, OUTPUT_DIR / f"{stem}.musicxml")
    files["musicxml"] = f"{stem}.musicxml"
    (OUTPUT_DIR / f"{stem}_歌詞.txt").write_text(lyric_sheet(song), encoding="utf-8")
    files["lyrics"] = f"{stem}_歌詞.txt"
    if audio:
        wav = OUTPUT_DIR / f"{stem}.wav"
        write_wav(render(arr, song.tempo, mute), wav)
        files["wav"] = wav.name
        if wav_to_mp3(wav, OUTPUT_DIR / f"{stem}.mp3"):
            files["mp3"] = f"{stem}.mp3"
    return files


def save_song_text(name: str, text: str) -> Path:
    yaml.safe_load(text)  # 構文チェック
    SONGS_DIR.mkdir(exist_ok=True)
    p = SONGS_DIR / f"{safe_name(name)}.yaml"
    p.write_text(text, encoding="utf-8")
    return p


__all__ = ["kaeuta", "song_view", "render_song", "save_song_text", "dump_yaml", "safe_name", "save_song_dict"]
