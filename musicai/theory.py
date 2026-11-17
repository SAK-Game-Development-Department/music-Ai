"""音楽理論の基本: 音名・音階・キー・コード・ディグリー。"""
from __future__ import annotations

import re
from dataclasses import dataclass

NOTE_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

SCALES = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
}

CHORD_QUALITIES = {
    "": [0, 4, 7],
    "m": [0, 3, 7],
    "7": [0, 4, 7, 10],
    "maj7": [0, 4, 7, 11],
    "M7": [0, 4, 7, 11],
    "m7": [0, 3, 7, 10],
    "mM7": [0, 3, 7, 11],
    "6": [0, 4, 7, 9],
    "m6": [0, 3, 7, 9],
    "9": [0, 4, 7, 10, 14],
    "add9": [0, 4, 7, 14],
    "madd9": [0, 3, 7, 14],
    "dim": [0, 3, 6],
    "dim7": [0, 3, 6, 9],
    "m7b5": [0, 3, 6, 10],
    "aug": [0, 4, 8],
    "sus2": [0, 2, 7],
    "sus4": [0, 5, 7],
    "7sus4": [0, 5, 7, 10],
}

# よく使われるコード進行（メジャーキー基準のディグリー表記）
PROGRESSIONS = {
    "王道進行": ("IV V iii vi", "切なくエモい。サビの定番"),
    "カノン進行": ("I V vi iii IV I IV V", "壮大・感動的"),
    "小室進行": ("vi IV V I", "疾走感と切なさ"),
    "ポップパンク進行": ("I V vi IV", "明るく前向き"),
    "丸サ進行": ("IVmaj7 III7 vi7 v7 I7", "おしゃれ・シティポップ"),
    "JustTheTwoOfUs進行": ("IVmaj7 III7 vi7 vi7", "都会的・切ない"),
    "456進行": ("IV V vi vi", "盛り上がり→切なさ"),
    "Bメロ定番": ("vi IV I V", "サビ前の盛り上げ"),
    "王道Aメロ": ("I vi IV V", "50年代風・安心感"),
    "下降進行": ("I V/vii vi I/v IV I/iii ii V", "ベースが下がっていく。しっとり"),
    "ドミナント終止": ("ii V I I", "しっかり終わる"),
}


def pc_name(pc: int, prefer_flat: bool = False) -> str:
    return (FLAT_NAMES if prefer_flat else SHARP_NAMES)[pc % 12]


def parse_pc(name: str) -> int:
    m = re.fullmatch(r"([A-Ga-g])([#b♯♭]*)", name.strip())
    if not m:
        raise ValueError(f"音名が読めません: {name!r}")
    pc = NOTE_PC[m.group(1).upper()]
    for acc in m.group(2):
        pc += 1 if acc in "#♯" else -1
    return pc % 12


def parse_pitch(text: str) -> int:
    """'C4' -> 60, 'F#3' -> 54, 'Bb4' -> 70."""
    m = re.fullmatch(r"([A-Ga-g][#b♯♭]*)(-?\d)", text.strip())
    if not m:
        raise ValueError(f"音の高さが読めません: {text!r}（例: C4, F#3, Bb4）")
    pc_raw = NOTE_PC[m.group(1)[0].upper()]
    for acc in m.group(1)[1:]:
        pc_raw += 1 if acc in "#♯" else -1
    return 12 * (int(m.group(2)) + 1) + pc_raw


def pitch_name(midi: int, prefer_flat: bool = False) -> str:
    return f"{pc_name(midi % 12, prefer_flat)}{midi // 12 - 1}"


@dataclass(frozen=True)
class Key:
    tonic: int  # pitch class
    mode: str  # major / minor

    @property
    def scale_pcs(self) -> list[int]:
        return [(self.tonic + i) % 12 for i in SCALES[self.mode]]

    @property
    def prefer_flat(self) -> bool:
        major_tonic = self.tonic if self.mode == "major" else (self.tonic + 3) % 12
        return major_tonic in (5, 10, 3, 8, 1, 6)

    @property
    def fifths(self) -> int:
        major_tonic = self.tonic if self.mode == "major" else (self.tonic + 3) % 12
        table = {0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: 6, 5: -1, 10: -2, 3: -3, 8: -4, 1: -5}
        return table[major_tonic]

    @property
    def major_tonic(self) -> int:
        return self.tonic if self.mode == "major" else (self.tonic + 3) % 12

    def name(self) -> str:
        return f"{pc_name(self.tonic, self.prefer_flat)} {self.mode}"


def parse_key(text: str) -> Key:
    t = text.strip()
    m = re.fullmatch(r"([A-Ga-g][#b♯♭]?)\s*(major|minor|maj|min|m|M)?", t)
    if not m:
        raise ValueError(f"キーが読めません: {text!r}（例: C major, A minor, Am）")
    mode_raw = m.group(2) or "major"
    mode = "minor" if mode_raw in ("minor", "min", "m") else "major"
    return Key(parse_pc(m.group(1)), mode)


@dataclass(frozen=True)
class Chord:
    name: str
    root: int  # pc
    intervals: tuple[int, ...]
    bass: int  # pc

    @property
    def pcs(self) -> list[int]:
        return sorted({(self.root + i) % 12 for i in self.intervals})


_CHORD_RE = re.compile(r"([A-G][#b]?)([^/]*)(?:/([A-G][#b]?))?")


def parse_chord(text: str) -> Chord:
    m = _CHORD_RE.fullmatch(text.strip())
    if not m:
        raise ValueError(f"コードが読めません: {text!r}")
    root = parse_pc(m.group(1))
    qual = m.group(2)
    if qual not in CHORD_QUALITIES:
        aliases = {"min": "m", "-": "m", "M": "", "maj": "", "min7": "m7", "-7": "m7",
                   "ø": "m7b5", "o": "dim", "°": "dim", "+": "aug", "sus": "sus4"}
        if qual in aliases:
            qual = aliases[qual]
        else:
            raise ValueError(f"コードの種類が読めません: {text!r}（対応: {', '.join(k or 'メジャー' for k in CHORD_QUALITIES)}）")
    bass = parse_pc(m.group(3)) if m.group(3) else root
    return Chord(text.strip(), root, tuple(CHORD_QUALITIES[qual]), bass)


_ROMAN = ["VII", "VI", "IV", "V", "III", "II", "I"]
_ROMAN_DEG = {"I": 0, "II": 1, "III": 2, "IV": 3, "V": 4, "VI": 5, "VII": 6}
_ROMAN_RE = re.compile(r"([b#]?)(VII|VI|IV|V|III|II|I|vii|vi|iv|v|iii|ii|i)([^/]*)(?:/(.+))?")


def roman_to_pc(numeral: str, key: Key) -> tuple[int, bool, str]:
    """ディグリーの度数を (pc, is_minor_case, 残り) に。メジャースケール基準 + b/#。"""
    m = _ROMAN_RE.fullmatch(numeral)
    if not m:
        raise ValueError(f"ディグリーが読めません: {numeral!r}（例: I, vi, IVmaj7, bVII）")
    acc, rn, suffix, _ = m.groups()
    deg = _ROMAN_DEG[rn.upper()]
    pc = (key.tonic + SCALES["major"][deg] + (1 if acc == "#" else -1 if acc == "b" else 0)) % 12
    return pc, rn.islower(), suffix


def roman_to_chord_name(token: str, key: Key) -> str:
    """'vi' -> 'Am'（キーC）。'V/vii' のような転回指定も可（/の後はベース音のディグリー）。"""
    m = _ROMAN_RE.fullmatch(token)
    if not m:
        raise ValueError(f"ディグリーが読めません: {token!r}")
    main = token.split("/")[0]
    pc, minor, suffix = roman_to_pc(main, key)
    if suffix in ("°", "o"):
        suffix = "dim"
    if minor and not suffix.startswith(("dim", "m7b5", "ø")):
        if suffix == "":
            qual = "m"
        elif suffix in ("7", "6", "add9", "M7", "maj7"):
            qual = {"7": "m7", "6": "m6", "add9": "madd9", "M7": "mM7", "maj7": "mM7"}[suffix]
        else:
            qual = "m" + suffix if not suffix.startswith("m") else suffix
    else:
        qual = suffix
    name = pc_name(pc, key.prefer_flat) + qual
    if m.group(4):
        bpc, _, _ = roman_to_pc(m.group(4), key)
        name += "/" + pc_name(bpc, key.prefer_flat)
    return name


def progression_to_chords(prog: str, key: Key) -> list[str]:
    """'王道進行' または 'IV V iii vi' または 'C G Am F' をコード名リストへ。

    マイナーキーで定番進行名を使った場合は平行調（メジャー）基準で解釈する。
    """
    text = prog.strip()
    if text in PROGRESSIONS:
        text = PROGRESSIONS[text][0]
        key = Key(key.major_tonic, "major")
    out = []
    for tok in text.replace("|", " ").split():
        if tok[0] in "IViv" or (tok[0] in "b#" and len(tok) > 1 and tok[1] in "IViv"):
            out.append(roman_to_chord_name(tok, key))
        else:
            parse_chord(tok)  # 検証
            out.append(tok)
    return out


def scale_pitches(key: Key, lo: int, hi: int) -> list[int]:
    pcs = set(key.scale_pcs)
    return [p for p in range(lo, hi + 1) if p % 12 in pcs]
