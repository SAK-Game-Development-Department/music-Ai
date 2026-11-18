"""曲データ（YAML）の読み書きと検証。

曲ファイルの形式（例）::

    title: ほしのうた
    key: C major
    tempo: 100
    time: 4/4
    style: pop            # pop / ballad / rock / simple
    structure: [intro, A, A2, outro]
    sections:
      A:
        chords: "C | F C | F C | G C"        # | で小節区切り。小節内はスペースで均等割り
        melody: "C4:1 C4 G4 G4 | A4 A4 G4:2"  # 音名:拍数。r=休符。拍数省略で直前と同じ
        lyrics: "ほしがひかる / ..."
      A2:
        base: A               # A のメロディとコードを引き継ぐ（2番など）
        lyrics: "..."         # 歌詞だけ替える。モーラ数が違えば自動でメロディを調整
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import yaml

from .lyrics import Syllable, split_mora
from .theory import Key, parse_chord, parse_key, parse_pitch, pitch_name, progression_to_chords


class SongError(ValueError):
    pass


@dataclass
class Note:
    pitch: int | None  # None = 休符
    dur: Fraction  # 拍数
    lyric: Syllable | None = None
    melisma: bool = False  # True = 新しい歌詞を割り当てず、前の文字を伸ばしたまま音程を変える

    @property
    def is_rest(self) -> bool:
        return self.pitch is None


@dataclass
class Section:
    name: str
    chords: list[tuple[Fraction, Fraction, str]]  # (開始拍, 長さ, コード名) セクション内
    notes: list[Note]
    bars: int
    lyrics_text: str = ""
    energy: str = "mid"
    sing: bool = True  # False = 歌わないパート（間奏など）
    raw: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def length(self) -> Fraction:
        return Fraction(0) if not self.chords else self.chords[-1][0] + self.chords[-1][1]


@dataclass
class Song:
    title: str
    key: Key
    tempo: float
    beats_per_bar: int
    style: str
    structure: list[str]
    sections: dict[str, Section]
    raw: dict

    def timeline(self):
        """(開始拍, Section) を構成順に返す。"""
        t = Fraction(0)
        for name in self.structure:
            sec = self.sections[name]
            yield t, sec
            t += sec.length

    @property
    def total_beats(self) -> Fraction:
        return sum((s.length for _, s in self.timeline()), Fraction(0))


def parse_dur(text: str) -> Fraction:
    try:
        return Fraction(text)
    except (ValueError, ZeroDivisionError):
        raise SongError(f"拍数が読めません: {text!r}（例: 1, 0.5, 1/2, 1.5）")


def parse_melody(text: str, beats_per_bar: int) -> tuple[list[Note], list[str]]:
    notes: list[Note] = []
    warnings: list[str] = []
    dur = Fraction(1)
    pos = Fraction(0)
    bar_no = 1
    for tok in (text or "").split():
        if tok == "|":
            # 小節線の位置が小節の区切りと合っているか（小節をまたぐ音は OK）
            if pos % beats_per_bar != 0:
                warnings.append(f"{bar_no}本目の小節線の位置がずれています（{float(pos):g} 拍目）")
            bar_no += 1
            continue
        mel = tok.endswith("~")
        tok = tok.rstrip("~")
        if ":" in tok:
            p, d = tok.split(":", 1)
            dur = parse_dur(d)
        else:
            p = tok
        pitch = None if p.lower() in ("r", "rest", "-") else parse_pitch(p)
        notes.append(Note(pitch, dur, melisma=mel and pitch is not None))
        pos += dur
    return notes, warnings


def melody_to_text(notes: list[Note], beats_per_bar: int, prefer_flat: bool = False) -> str:
    """Note リスト → メロディ文字列（小節線付き）。小節をまたぐ音はそのまま書く。"""
    out = []
    pos = Fraction(0)
    last_dur = None
    for n in notes:
        name = "r" if n.pitch is None else pitch_name(n.pitch, prefer_flat)
        if n.dur != last_dur:
            d = n.dur
            ds = str(d.numerator) if d.denominator == 1 else (f"{float(d):g}" if d.denominator in (2, 4, 8) else str(d))
            name += f":{ds}"
            last_dur = n.dur
        if n.melisma:
            name += "~"
        out.append(name)
        pos += n.dur
        if pos % beats_per_bar == 0:
            out.append("|")
    if out and out[-1] == "|":
        out.pop()
    return " ".join(out)


def parse_chords(text: str, key: Key, beats_per_bar: int) -> list[tuple[Fraction, Fraction, str]]:
    """'C | F C | G' → [(0,4,C),(4,2,F),(6,2,C),(8,4,G)]。

    | がない場合は 1 トークン = 1 小節。ディグリー（I V vi IV）や進行名も可。
    """
    text = (text or "").strip()
    if not text:
        return []
    if "|" in text:
        bars = [b.split() for b in text.split("|")]
    else:
        bars = [[t] for t in text.split()]
    out = []
    t = Fraction(0)
    for bar in bars:
        if not bar:
            continue
        names = []
        for tok in bar:
            names.extend(progression_to_chords(tok, key) if tok not in ("%",) else ["%"])
        each = Fraction(beats_per_bar, len(names))
        for nm in names:
            if nm == "%":  # 前のコードを継続
                if out:
                    s, d, prev = out[-1]
                    out[-1] = (s, d + each, prev)
                t += each
                continue
            parse_chord(nm)
            out.append((t, each, nm))
            t += each
    return out


def default_energy(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ("chorus", "sabi", "サビ", "hook")):
        return "high"
    if any(k in n for k in ("intro", "outro", "イントロ", "アウトロ", "ending")):
        return "low"
    if any(k in n for k in ("pre", "b", "bridge", "bメロ", "inter", "間奏", "solo")):
        return "mid"
    return "low"


def attach_lyrics(notes: list[Note], text: str, section: str) -> list[str]:
    """音符に歌詞を割り当てる。返り値は警告。"""
    syls = split_mora(text or "")
    sung = [n for n in notes if not n.is_rest and not n.melisma]
    warns = []
    if syls and len(syls) != len(sung):
        warns.append(
            f"[{section}] 音符 {len(sung)} 個に対して歌詞 {len(syls)} 個（モーラ+~）。"
            f"{'歌詞が多い' if len(syls) > len(sung) else '歌詞が少ない'}です。"
            " `kaeuta` コマンドか `fit: true` で自動調整できます。"
        )
    for n, s in zip(sung, syls):
        n.lyric = s
    prev = None
    for n in notes:
        if n.is_rest:
            continue
        if n.melisma:
            n.lyric = Syllable("~", prev.phrase if prev else 0, True)
        elif n.lyric is not None:
            prev = n.lyric
    return warns


def _resolve_spec(name: str, all_specs: dict, depth: int = 0) -> dict:
    """base: を辿って設定をマージする。"""
    if depth > 8:
        raise SongError(f"base の参照がループしています: {name}")
    spec = dict(all_specs.get(name) or {})
    base = spec.pop("base", None)
    if base is None:
        return spec
    if base not in all_specs:
        raise SongError(f"[{name}] base: {base} が見つかりません")
    merged = _resolve_spec(base, all_specs, depth + 1)
    merged.pop("fit", None)
    merged.update(spec)
    return merged


def _build_section(name: str, all_specs: dict, key: Key, bpb: int) -> Section:
    from .kaeuta import fit_lyrics  # 循環 import 回避

    spec = _resolve_spec(name, all_specs)
    chords = parse_chords(spec.get("chords", ""), key, bpb)
    notes, warns = parse_melody(spec.get("melody", ""), bpb)
    warns = [f"[{name}] {w}" for w in warns]
    mel_len = sum((n.dur for n in notes), Fraction(0))
    if not chords:
        bars = int(spec.get("bars", 0)) or max(1, -(-mel_len // bpb))
        chords = [(Fraction(i * bpb), Fraction(bpb), "N.C.") for i in range(int(bars))]
    length = chords[-1][0] + chords[-1][1]
    if notes and mel_len != length:
        if mel_len < length:
            notes.append(Note(None, length - mel_len))
        else:
            warns.append(f"[{name}] メロディ（{float(mel_len):g} 拍）がコード（{float(length):g} 拍）より長いです")
    lyrics = spec.get("lyrics", "") or ""
    if spec.get("fit") and lyrics and notes:
        notes, report = fit_lyrics(notes, lyrics)
        warns.extend(f"[{name}] {r}" for r in report if r.startswith("⚠"))
    else:
        warns.extend(attach_lyrics(notes, lyrics, name))
    return Section(
        name=name,
        chords=chords,
        notes=notes,
        bars=int(length // bpb),
        lyrics_text=lyrics,
        energy=spec.get("energy", default_energy(name)),
        sing=spec.get("sing", True) is not False,
        raw=spec,
        warnings=warns,
    )


def load_song(path: str | Path) -> Song:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return song_from_dict(data)


def song_from_dict(data: dict) -> Song:
    data = copy.deepcopy(data)
    key = parse_key(str(data.get("key", "C major")))
    time = str(data.get("time", "4/4"))
    bpb = int(time.split("/")[0])
    specs = data.get("sections") or {}
    if not specs:
        raise SongError("sections がありません")
    structure = data.get("structure") or list(specs)
    for s in structure:
        if s not in specs:
            raise SongError(f"structure の {s!r} が sections にありません")
    sections = {n: _build_section(n, specs, key, bpb) for n in dict.fromkeys(structure)}
    return Song(
        title=str(data.get("title", "untitled")),
        key=key,
        tempo=float(data.get("tempo", 120)),
        beats_per_bar=bpb,
        style=str(data.get("style", "pop")),
        structure=list(structure),
        sections=sections,
        raw=data,
    )


def save_song_dict(data: dict, path: str | Path) -> None:
    class _D(yaml.SafeDumper):
        pass

    def _str(dumper, s):
        if "\n" in s:
            return dumper.represent_scalar("tag:yaml.org,2002:str", s, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", s)

    _D.add_representer(str, _str)
    Path(path).write_text(
        yaml.dump(data, Dumper=_D, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8",
    )


def check_report(song: Song) -> str:
    lines = [f"♪ {song.title}  key={song.key.name()}  tempo={song.tempo:g}  {song.beats_per_bar}/4  style={song.style}"]
    total = song.total_beats * 60 / Fraction(song.tempo).limit_denominator()
    lines.append(f"  構成: {' → '.join(song.structure)}  （約 {int(total)//60}:{int(total)%60:02d}）")
    for name, sec in song.sections.items():
        sung = [n for n in sec.notes if not n.is_rest and not n.melisma]
        mora = len(split_mora(sec.lyrics_text)) if sec.lyrics_text else 0
        pitches = [n.pitch for n in sec.notes if not n.is_rest]
        rng = f"{pitch_name(min(pitches))}〜{pitch_name(max(pitches))}" if pitches else "-"
        ok = "OK" if (not mora or mora == len(sung)) else "要調整"
        lines.append(
            f"  [{name}] {sec.bars}小節 energy={sec.energy} 歌う音符{len(sung)} 歌詞{mora}モーラ 音域{rng}  {ok}"
        )
    warns = [w for s in song.sections.values() for w in s.warnings]
    if warns:
        lines.append("警告:")
        lines.extend("  " + w for w in warns)
    return "\n".join(lines)
