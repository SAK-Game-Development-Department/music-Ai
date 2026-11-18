"""CLI とアプリ（GUI）で共通の処理。"""
from __future__ import annotations

import copy
import re
from fractions import Fraction
from pathlib import Path

import numpy as np
import yaml

from .lyrics import phrases, split_mora
from .song import Song, check_report, melody_to_text, parse_melody, save_song_dict, song_from_dict, _resolve_spec

import shutil
import sys

FROZEN = getattr(sys, "frozen", False)  # exe として動いているか
# RESOURCE_DIR: 同梱ファイル（画面・サンプル曲）。DATA_DIR: 保存先（exe の隣）
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
DATA_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        t = d / ".write_test"
        t.write_text("ok")
        t.unlink()
        return True
    except OSError:
        return False


# exe の隣に書き込めない場合（Mac のダウンロード直後・/usr/bin など）はホームフォルダへ
if FROZEN and not _writable(DATA_DIR):
    DATA_DIR = Path.home() / "music-Ai"
ROOT = DATA_DIR
SONGS_DIR = DATA_DIR / "songs"
SPECS_DIR = DATA_DIR / "specs"
OUTPUT_DIR = DATA_DIR / "output"


def ensure_data_dirs() -> None:
    """exe 初回起動時、サンプル曲を exe の隣の songs/ にコピーする。"""
    SONGS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bundled = RESOURCE_DIR / "songs"
    if FROZEN and bundled.is_dir() and not any(SONGS_DIR.glob("*.yaml")):
        for f in bundled.glob("*.yaml"):
            shutil.copy2(f, SONGS_DIR / f.name)


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


def _mel_phrase_counts(notes) -> list[int]:
    from .kaeuta import melody_phrases

    return [sum(1 for i in g if not notes[i].is_rest and not notes[i].melisma) for g in melody_phrases(notes)]


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
            "mel_phrases": _mel_phrase_counts(sec.notes),
            "has_melody": any(not n.is_rest for n in sec.notes),
        })
    warnings = [w for s in song.sections.values() for w in s.warnings]
    return {
        "title": song.title, "key": song.key.name(), "tempo": song.tempo, "style": song.style,
        "beats_per_bar": song.beats_per_bar, "structure": song.structure, "timeline": timeline,
        "sections": secs, "warnings": warnings, "report": check_report(song),
        "duration_sec": float(song.total_beats) * 60 / song.tempo,
        "accompaniment": accompaniment_mode(song),
        "source": _source_view(song),
    }


def _source_view(song: Song) -> dict | None:
    src = source_info(song)
    if not src:
        return None
    orig = src.get("original")
    rel = None
    if orig and Path(orig).is_file() and Path(orig).is_relative_to(DATA_DIR):
        rel = Path(orig).relative_to(DATA_DIR).as_posix()
    return {"from": song.raw["source"].get("from"), "offset": src["offset"], "original_url": "/data/" + rel if rel else None}


def source_info(song: Song) -> dict | None:
    """取り込んだ曲なら、元音源の情報 {backing, original, offset} を返す（パスは絶対パス）。"""
    src = song.raw.get("source")
    if not isinstance(src, dict) or not src.get("backing"):
        return None
    out = dict(src)
    for k in ("backing", "original"):
        if out.get(k):
            p = Path(out[k])
            out[k] = p if p.is_absolute() else DATA_DIR / p
    out["offset"] = float(out.get("offset", 0))
    return out


def accompaniment_mode(song: Song) -> str:
    """generated（自動アレンジ）/ source（元の音源）/ both"""
    mode = str(song.raw.get("accompaniment", "source" if source_info(song) else "generated"))
    return mode if mode in ("generated", "source", "both") else "generated"


def render_song(song: Song, stem: str, mute: set[str] | None = None, audio: bool = True,
                out_dir: Path | None = None) -> dict:
    from .arrange import Arrangement, arrange
    from .export import lyric_sheet, write_midi, write_musicxml
    from .synth import SR, render, wav_to_mp3, write_wav

    out_dir = Path(out_dir or OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    arr = arrange(song)
    files = {}
    write_midi(song, arr, out_dir / f"{stem}.mid")
    files["midi"] = f"{stem}.mid"
    write_musicxml(song, out_dir / f"{stem}.musicxml")
    files["musicxml"] = f"{stem}.musicxml"
    (out_dir / f"{stem}_歌詞.txt").write_text(lyric_sheet(song), encoding="utf-8")
    files["lyrics"] = f"{stem}_歌詞.txt"
    if audio:
        backing = None
        src = source_info(song)
        mode = accompaniment_mode(song)
        if src and mode in ("source", "both") and Path(src["backing"]).is_file():
            from .audio_io import load_audio

            dur = float(song.total_beats) * 60 / song.tempo + 2.0
            backing = load_audio(src["backing"], SR, src["offset"], src["offset"] + dur, channels=2)
            # 最後の 2 秒はフェードアウト
            fade = min(backing.shape[1], 2 * SR)
            backing[:, -fade:] *= np.linspace(1, 0, fade)
            if mode == "source":
                arr = Arrangement({k: v for k, v in arr.tracks.items() if k == "vocal"}, arr.total_beats)
        wav = out_dir / f"{stem}.wav"
        write_wav(render(arr, song.tempo, mute, backing=backing), wav)
        files["wav"] = wav.name
        if wav_to_mp3(wav, out_dir / f"{stem}.mp3"):
            files["mp3"] = f"{stem}.mp3"
    return files


# ---------------------------------------------------------------- 取り込み（YouTube / 音声ファイル）
IMPORTS_DIR = DATA_DIR / "imports"


def import_song(source: str, start: float = 0.0, end: float | None = None, title: str | None = None,
                progress=None) -> dict:
    """YouTube URL か音声ファイルから曲を起こして songs/ に保存。{name, title, log} を返す。"""
    import time

    from .audio_io import download_audio, is_url
    from .transcribe import analysis_to_song, analyze, make_karaoke, separate_demucs

    def say(m):
        if progress:
            progress(m)

    work = IMPORTS_DIR / time.strftime("%Y%m%d-%H%M%S")
    work.mkdir(parents=True, exist_ok=True)
    if is_url(source):
        say("ダウンロードしています…")
        path, got_title = download_audio(source.strip(), work, progress)
    else:
        path = Path(source)
        if not path.is_file():
            raise ValueError(f"ファイルが見つかりません: {source}")
        got_title = path.stem
    title = (title or "").strip() or got_title
    start = max(0.0, float(start or 0))
    end = float(end) if end else None
    if end is not None and end <= start + 5:
        raise ValueError("範囲が短すぎます（5 秒以上にしてください）")

    vocals = None
    sep = None
    from .transcribe import demucs_available

    if demucs_available():
        say("ボーカルを分離しています（demucs）…数分かかることがあります")
        sep = separate_demucs(path, work / "sep")
        if sep:
            vocals = sep[0]
    an = analyze(path, start, end, vocals_path=vocals, progress=progress)

    say("カラオケ音源を作っています…")
    from .audio_io import load_audio, save_wav

    backing = work / "backing.wav"
    if sep:
        save_wav(load_audio(sep[1], 44100, start, end), backing, 44100)
    else:
        make_karaoke(path, backing, start, end)
    original = work / "original.wav"
    save_wav(load_audio(path, 44100, start, end), original, 44100)

    data = analysis_to_song(an, title)
    rel = lambda p: p.relative_to(DATA_DIR).as_posix() if p.is_relative_to(DATA_DIR) else str(p)
    data["accompaniment"] = "source"
    data["source"] = {
        "from": source if is_url(source) else Path(source).name,
        "range": [round(start, 2), round(end, 2) if end else None],
        "backing": rel(backing),
        "original": rel(original),
        "offset": round(float(an.t0), 4),
    }
    data = {"_note": "音源から自動で起こした曲。音符の高さ・長さは推定なので、聴き比べて直してください", **data}
    name = save_song_text(title, dump_yaml(data)).stem
    say("できました")
    return {"name": name, "title": title, "log": an.log + (["カラオケ: demucs で分離"] if sep else ["カラオケ: 中央のボーカル帯域を弱めた簡易版"])}


def save_song_text(name: str, text: str) -> Path:
    from .migrate import migrate_text
    from .schema import validate_data

    data = yaml.safe_load(text)  # 構文チェック
    if not isinstance(data, dict):
        raise ValueError("曲データの形式が正しくありません")
    text, _, _ = migrate_text(text)  # 古い形式には schema_version を補う（コメントは保つ）
    result = validate_data(yaml.safe_load(text), "song")
    if not result.ok:
        raise ValueError("曲データの形式が正しくありません:\n" + result.format())
    SONGS_DIR.mkdir(exist_ok=True)
    p = SONGS_DIR / f"{safe_name(name)}.yaml"
    p.write_text(text, encoding="utf-8")
    return p


__all__ = ["kaeuta", "song_view", "render_song", "save_song_text", "dump_yaml", "safe_name", "save_song_dict"]
