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

import os
import shutil
import sys

FROZEN = getattr(sys, "frozen", False)  # exe として動いているか
# RESOURCE_DIR: 同梱ファイル（画面・サンプル曲）。DATA_DIR: 保存先（exe の隣）
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
DATA_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
# MUSICAI_HOME を指定すると、保存先（songs/・output/ など）をそこにできる。
# ソースが書き込めない場所（Nix のパッケージなど）から動かすときに使う。
if os.environ.get("MUSICAI_HOME"):
    DATA_DIR = Path(os.environ["MUSICAI_HOME"]).expanduser().resolve()


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
PROPOSALS_DIR = DATA_DIR / "proposals"  # AI の修正案（採用するまで曲には反映しない）
OUTPUT_DIR = DATA_DIR / "output"


def ensure_data_dirs() -> None:
    """初回起動時、保存先がソースと別の場所（exe の隣・MUSICAI_HOME）なら、サンプル曲を songs/ にコピーする。"""
    SONGS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bundled = RESOURCE_DIR / "songs"
    if (FROZEN or DATA_DIR.resolve() != RESOURCE_DIR.resolve()) and bundled.is_dir() and not any(SONGS_DIR.glob("*.yaml")):
        for f in bundled.glob("*.yaml"):
            shutil.copyfile(f, SONGS_DIR / f.name)  # 内容だけ（権限は引き継がない。Nix のストアは読み取り専用）


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


def auto_lyrics(data: dict, story: bool = True, theme: str | None = None, seed: int | None = None,
                keep: dict[str, str] | None = None) -> tuple[dict[str, str], str]:
    """歌詞を自動で作る。keep に歌詞があるセクションはそのまま（空のセクションだけ作る）。"""
    from .lyricgen import generate, phrase_counts

    song = song_from_dict(data)
    keep = {k: v for k, v in (keep or {}).items() if (v or "").strip() and song.sections.get(k)
            and song.sections[k].sing}
    counts, originals = phrase_counts(song, with_originals=True)
    todo = [(n, c) for n, c in counts if n not in keep]
    made, used_theme = generate(todo, story=story, theme=theme, seed=seed, originals=originals)
    return {**made, **keep}, used_theme


def apply_sing(data: dict, sing: dict[str, bool] | None) -> dict:
    """パートごとの「歌う / 歌わない（間奏）」の切り替えを曲 dict に反映したコピーを返す。"""
    new = copy.deepcopy(data)
    for name, on in (sing or {}).items():
        sec = (new.get("sections") or {}).get(name)
        if sec is None:
            raise ValueError(f"セクション {name!r} がありません")
        if on:
            sec.pop("sing", None)
        else:
            sec["sing"] = False
    return new


def kaeuta(data: dict, new_lyrics: dict[str, str], title: str | None = None,
           sing: dict[str, bool] | None = None) -> tuple[dict, list[str]]:
    """曲 dict の各セクションの歌詞を差し替え、メロディを合わせた新しい dict と報告を返す。

    sing: パート名 → 歌うか（False のパートは間奏として、歌詞を付けず歌わせない）。
    """
    from .kaeuta import fit_lyrics

    data = apply_sing(data, sing)
    song = song_from_dict(data)
    new = copy.deepcopy(data)
    new["title"] = title or f"{data.get('title', '')}（替え歌）"
    report: list[str] = []
    for sec_name, text in new_lyrics.items():
        if not (text or "").strip():
            continue
        if (data["sections"].get(sec_name) or {}).get("sing") is False:
            continue  # 歌わないパートには歌詞を付けない
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


def _lyrics_lines(text: str) -> list[str]:
    from .lyrics import display_lyrics

    return display_lyrics(text) if text else []


def _mel_phrase_counts(notes) -> list[int]:
    from .kaeuta import melody_phrases

    from .kaeuta import merge_small_phrases

    return [sum(1 for i in g if not notes[i].is_rest and not notes[i].melisma)
            for g in merge_small_phrases(notes, melody_phrases(notes))]


def song_view(song: Song) -> dict:
    """GUI 表示用: セクション・ピアノロール・歌詞情報。"""
    from .lyricgen import phrase_counts

    try:
        fit_counts = dict(phrase_counts(song))  # 替え歌で歌詞を合わせる元のメロディの、フレーズごとの数
    except Exception:
        fit_counts = {}
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
            "lyrics_lines": _lyrics_lines(sec.lyrics_text),
            "sung": sum(1 for n in sec.notes if not n.is_rest and not n.melisma),
            "mel_phrases": _mel_phrase_counts(sec.notes),
            "fit_counts": fit_counts.get(name),
            "has_melody": any(not n.is_rest for n in sec.notes),
            "sing": sec.sing,
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
                progress=None, subtitles: str | Path | None = None, lyrics: str | None = None,
                whisper: bool = False, whisper_model: str | None = None) -> dict:
    """YouTube URL か音声ファイルから曲を起こして songs/ に保存。{name, title, log} を返す。"""
    import time

    from .audio_io import download_audio, is_url
    from .transcribe import analysis_to_song, analyze, make_karaoke, separate_demucs

    def say(m):
        if progress:
            progress(m)

    work = IMPORTS_DIR / time.strftime("%Y%m%d-%H%M%S")
    work.mkdir(parents=True, exist_ok=True)
    subs = Path(subtitles) if subtitles else None  # 歌詞の字幕ファイル（.vtt / .srt）を直接わたすこともできる
    if is_url(source):
        say("ダウンロードしています…")
        path, got_title = download_audio(source.strip(), work, progress)
        from .audio_io import find_subtitles

        subs = subs or find_subtitles(work)
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

    lyric_log: list[str] = []
    cues = []
    if subs is not None:
        from .origlyrics import parse_subtitles

        bar_sec = 4 * 60 / an.tempo
        for s0, e0, text in parse_subtitles(subs):
            s1, e1 = s0 - start, e0 - start
            if end is not None and s1 > end - start:
                continue
            if e1 <= 0:
                continue
            cues.append(((max(0.0, s1) - an.t0) / bar_sec, (e1 - an.t0) / bar_sec, text))
        if cues:
            covered = [False] * an.bars
            for b_s, b_e, _ in cues:
                for b in range(max(0, int(b_s)), min(an.bars, int(b_e - 1e-6) + 1)):
                    covered[b] = True
            an.bar_vocal = covered  # 字幕の出ている小節 = 歌（音からの推定より確か）
            lyric_log.append(f"YouTube の字幕から原曲の歌詞を {len(cues)} 行読み込みました（歌詞の出ていない所は間奏）")
    data = None
    if whisper:  # Whisper で、歌詞と「どのタイミングで歌っているか」を聴き取る
        known = [c[2] for c in cues] if cues else None
        if lyrics and lyrics.strip():
            from .origlyrics import lyric_lines

            known = [ln for b in lyric_lines(lyrics) for ln in b]
        data, wlog = _whisper_song(an, title, path, start, end, vocals, known, whisper_model, say)
        lyric_log += wlog
    if data is None:
        data = analysis_to_song(an, title)
        if cues:
            _put_cues(data, cues)
        elif lyrics and lyrics.strip():  # 時間のない歌詞（貼り付け）
            data, rep = attach_original_lyrics(data, lyrics)
            lyric_log.append("貼り付けた原曲の歌詞をパートに入れました（歌詞のないパートは間奏）")
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
    return {"name": name, "title": title, "log": an.log + lyric_log
            + (["カラオケ: demucs で分離"] if sep else ["カラオケ: 中央のボーカル帯域を弱めた簡易版"])}


def to_ruby_safe(text: str) -> str:
    """漢字の読みを {漢字|よみ} にする（読みが調べられないときはそのまま）。"""
    from .reading import ReadingUnavailable, to_ruby

    try:
        return to_ruby(text)
    except ReadingUnavailable:
        return text


def _whisper_song(an, title, path, start, end, vocals, known_lines, model, say) -> tuple[dict | None, list[str]]:
    """Whisper で歌詞の時刻を聴き取り、その時刻に音符を置いた曲 dict を作る。失敗したら (None, 理由)。"""
    from . import asr
    from .lyricsync import align_known, build_song, lines_from_asr
    from .transcribe import vocal_focus

    try:
        audio = vocal_focus(path, start, end, vocals)
        prompt = "".join(known_lines) if known_lines else None
        segs = asr.transcribe(audio, model or asr.DEFAULT_MODEL, prompt=prompt, progress=say)
    except asr.AsrUnavailable as e:
        return None, [f"Whisper は使えませんでした（{e}）。音からの推定で作りました"]
    except Exception as e:  # noqa: BLE001  モデルのダウンロード失敗など
        return None, [f"Whisper で聴き取れませんでした（{str(e)[:120]}）。音からの推定で作りました"]
    if not segs:
        return None, ["Whisper で歌詞が聴き取れませんでした。音からの推定で作りました"]
    log = []
    timed = align_known(known_lines, segs) if known_lines else None
    if timed:
        hit = sum(t.matched * len(t.mora) for t in timed) / max(1, sum(len(t.mora) for t in timed))
        log.append(f"Whisper で原曲の歌詞 {len(timed)} 行の歌い出しのタイミングを合わせました"
                   f"（Whisper の聴き取りと一致したモーラ {hit:.0%}）")
    else:
        if known_lines:
            log.append("原曲の歌詞と Whisper の聴き取りがほとんど一致しなかったので、聴き取った歌詞を使いました")
        timed = lines_from_asr(segs)
        if not timed:
            return None, ["Whisper で歌詞が聴き取れませんでした。音からの推定で作りました"]
        log.append(f"Whisper で歌詞を {len(timed)} 行聴き取りました（例:「{timed[0].text}」）。違う所は曲データで直せます")
    try:
        return build_song(an, title, timed), log
    except ValueError as e:
        return None, log + [f"タイミングを合わせられませんでした（{e}）。音からの推定で作りました"]


def whisper_resync(data: dict, lyrics: str | None = None, model: str | None = None, progress=None) -> tuple[dict, list[str]]:
    """取り込み済みの曲を、元の音源から Whisper で歌詞のタイミングを合わせ直した新しい曲 dict にする。

    lyrics（原曲の歌詞）を渡さなければ、曲に入っている原曲の歌詞を使う。
    """
    from .lyrics import display_lyrics
    from .transcribe import analyze

    src = source_info(song_from_dict(data))
    if not src or not src.get("original") or not Path(src["original"]).is_file():
        raise ValueError("この曲には元の音源がありません（YouTube・音声ファイルから取り込んだ曲で使えます）")
    say = progress or (lambda m: None)
    if lyrics and lyrics.strip():
        from .origlyrics import lyric_lines

        known = [ln for b in lyric_lines(lyrics) for ln in b]
    else:
        song = song_from_dict(data)
        known = [ln for n in dict.fromkeys(song.structure) for ln in display_lyrics(song.sections[n].lyrics_text or "")
                 if song.sections[n].sing] or None
    an = analyze(src["original"], progress=progress)
    new, log = _whisper_song(an, data.get("title", "untitled"), Path(src["original"]), 0.0, None, None, known,
                             model, say)
    if new is None:
        raise ValueError(" ".join(log))
    for k in ("accompaniment", "source"):
        if k in data:
            new[k] = copy.deepcopy(data[k])
    new["source"]["offset"] = round(float(an.t0), 4)  # 元の音源（範囲で切ったもの）の中で 1 小節目が始まる秒
    return new, log


def _section_bars(data: dict) -> list[tuple[str, int, int]]:
    """[(パート名, 開始小節, 終了小節)]（構成の順）。"""
    out, b = [], 0
    for name in data.get("structure") or list(data["sections"]):
        n = len([x for x in (data["sections"][name].get("chords") or "").split("|") if x.strip()]) or 1
        out.append((name, b, b + n))
        b += n
    return out


def _set_original(sec: dict, lines: list[str]) -> None:
    """パートに原曲の歌詞を入れる（読みは自動。メロディは歌詞に合わせて自動調整）。"""
    from .reading import ReadingUnavailable, to_ruby

    try:
        sec["lyrics"] = "\n".join(to_ruby(ln) for ln in lines)
    except ReadingUnavailable:
        sec["lyrics"] = "\n".join(lines)
    sec["fit"] = True
    sec.pop("sing", None)


def _put_cues(data: dict, cues: list[tuple[float, float, str]]) -> None:
    """時間つきの歌詞の行を、その時間のパートに入れる。"""
    spans = _section_bars(data)
    by_part: dict[str, list[str]] = {}
    for b_s, b_e, text in cues:
        mid = (b_s + b_e) / 2
        for name, s, e in spans:
            if s <= mid < e:
                by_part.setdefault(name, []).append(text)
                break
    for name, lines in by_part.items():
        sec = data["sections"][name]
        if sec.get("melody"):
            _set_original(sec, lines)


def attach_original_lyrics(data: dict, text: str) -> tuple[dict, list[str]]:
    """貼り付けた原曲の歌詞（時間なし）を、パートに順番どおり・長さが合うように入れる。

    歌詞が 1 行も入らなかったパートは間奏（歌わない）にする。返り値: (新しい曲 dict, 報告)
    """
    from .origlyrics import assign_lines, lyric_lines

    blocks = lyric_lines(text)
    if not blocks:
        raise ValueError("歌詞が空です")
    new = copy.deepcopy(data)
    song = song_from_dict(new)
    parts = []
    bars: list[int] = []
    for name in dict.fromkeys(song.structure):
        spec = _resolve_spec(name, new["sections"])
        notes, _ = parse_melody(spec.get("melody", ""), song.beats_per_bar)
        n = sum(1 for x in notes if not x.is_rest and not x.melisma)
        if n:
            parts.append((name, n, song.sections[name].sing))
            bars.append(max(1, int(song.sections[name].length // song.beats_per_bar)))
    if not parts:
        raise ValueError("メロディのあるパートがありません")
    assigned = assign_lines(parts, blocks, bars)
    report = []
    for name, n, _ in parts:
        sec = new["sections"][name]
        lines = assigned.get(name)
        if lines:
            _set_original(sec, lines)
            report.append(f"【{name}】{len(lines)} 行: " + " / ".join(lines))
        else:
            sec["sing"] = False
            sec.pop("lyrics", None)
            sec.pop("fit", None)
            report.append(f"【{name}】歌詞なし → 間奏（歌わない）")
    return new, report


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
