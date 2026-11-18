"""アレンジ: コード進行とセクションの盛り上がり(energy)から伴奏を作る。

楽器: vocal(メロディ) / piano / pad / guitar / bass / drums
盛り上がりは「楽器の数・音数」で作る（Aメロ薄め → サビ全部入り）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from .song import Song
from .theory import parse_chord

KICK, STICK, SNARE, HAT, OPEN_HAT, CRASH, TOM_H, TOM_L = 36, 37, 38, 42, 46, 49, 50, 45


@dataclass
class Event:
    start: float  # 拍
    dur: float  # 拍
    pitch: int
    vel: float  # 0..1
    vowel: str = "a"
    lyric: str = ""
    legato: bool = False


@dataclass
class Arrangement:
    tracks: dict[str, list[Event]] = field(default_factory=dict)
    total_beats: float = 0.0

    def add(self, track: str, ev: Event):
        self.tracks.setdefault(track, []).append(ev)


def _voicing(pcs: list[int], prev: list[int] | None, lo=53, hi=74) -> list[int]:
    cands = []
    pcs = pcs[:4]
    for r in range(len(pcs)):
        order = pcs[r:] + pcs[:r]
        for base in range(lo, lo + 12):
            if base % 12 == order[0]:
                v = [base]
                for pc in order[1:]:
                    p = v[-1] + 1
                    while p % 12 != pc:
                        p += 1
                    v.append(p)
                if v[-1] <= hi:
                    cands.append(v)
    if not cands:
        return sorted(lo + ((pc - lo) % 12) for pc in pcs)
    if prev is None:
        return min(cands, key=lambda v: abs(sum(v) / len(v) - 62))
    pc_ = sorted(prev)

    def move(v):
        a, b = sorted(v), pc_
        m = sum(abs(x - y) for x, y in zip(a, b))
        return m + abs(len(a) - len(b)) * 3 + abs(sum(v) / len(v) - 62) * 0.3

    return min(cands, key=move)


def _bass_note(pc: int, lo=36) -> int:
    p = lo + ((pc - lo) % 12)
    return p


def arrange(song: Song) -> Arrangement:
    arr = Arrangement()
    bpb = song.beats_per_bar
    style = song.style
    prev_voice = None
    timeline = list(song.timeline())
    prev_vowel = "a"
    for idx, (t0, sec) in enumerate(timeline):
        t0 = float(t0)
        e = sec.energy
        nxt = timeline[idx + 1][1] if idx + 1 < len(timeline) else None
        lvl = {"low": 0, "mid": 1, "high": 2}.get(e, 1)

        # --- メロディ ---（歌わないパートは鳴らさない）
        t = t0
        for n in (sec.notes if sec.sing else []):
            if not n.is_rest:
                syl = n.lyric
                vowel = syl.vowel if syl else "a"
                if vowel == "-":
                    vowel = prev_vowel
                else:
                    prev_vowel = vowel if vowel not in ("q",) else prev_vowel
                arr.add("vocal", Event(t, float(n.dur), n.pitch, 0.85,
                                       vowel=vowel, lyric=syl.text if syl else "",
                                       legato=bool(n.melisma)))
            t += float(n.dur)

        # --- コード楽器 / ベース ---
        for cs, cd, name in sec.chords:
            if name == "N.C.":
                continue
            ch = parse_chord(name)
            s = t0 + float(cs)
            d = float(cd)
            voice = _voicing(ch.pcs, prev_voice)
            prev_voice = voice
            root = _bass_note(ch.bass)
            fifth = _bass_note((ch.root + 7) % 12)
            if fifth < root:
                fifth += 12 if fifth + 12 <= 50 else 0

            if style == "simple":
                for p in voice:
                    arr.add("piano", Event(s, d, p, 0.45))
                arr.add("bass", Event(s, d, root, 0.6))
                continue

            # piano
            if style == "ballad" or (style == "pop" and lvl == 0):
                # アルペジオ
                arp = [root + 12] + voice + [voice[1] + 12] if len(voice) > 1 else voice
                pat = [0, 1, 2, 3, 2, 1, 2, 3] if len(arp) >= 4 else [0, 1, 2, 1]
                step = 0.5
                k = 0
                x = 0.0
                while x < d - 1e-6:
                    p = arp[pat[k % len(pat)] % len(arp)]
                    arr.add("piano", Event(s + x, min(step * 2, d - x), p, 0.40 + (0.08 if k % 4 == 0 else 0)))
                    x += step
                    k += 1
            elif style == "rock":
                power = [root + 12, root + 19, root + 24]
                x = 0.0
                while x < d - 1e-6:
                    for p in power:
                        arr.add("guitar", Event(s + x, 0.45, p, 0.5 if lvl else 0.35))
                    x += 0.5 if lvl else 1.0
            else:  # pop
                hits = {1: [(0, 1.5), (1.5, 1.0), (2.5, 0.5), (3, 1.0)],
                        2: [(0, 0.5), (0.5, 0.5), (1, 0.5), (1.5, 1.0), (2.5, 0.5), (3, 0.5), (3.5, 0.5)]}[lvl]
                for hs, hd in hits:
                    if hs < d - 1e-6:
                        for p in voice:
                            arr.add("piano", Event(s + hs, min(hd, d - hs), p, 0.38 + (0.07 if hs == 0 else 0)))

            if lvl >= 1 and style != "rock" or (style == "rock" and lvl == 2):
                for p in voice:
                    arr.add("pad", Event(s, d, p + 12 if style != "rock" else p, 0.20 + 0.06 * lvl))

            # bass
            if style == "ballad":
                arr.add("bass", Event(s, min(d, 2), root, 0.6))
                if d > 2:
                    arr.add("bass", Event(s + 2, d - 2, fifth if lvl else root, 0.5))
            else:
                step = {0: 2.0, 1: 1.0, 2: 0.5}[lvl] if style == "pop" else (0.5 if lvl else 1.0)
                x = 0.0
                k = 0
                while x < d - 1e-6:
                    p = root
                    if style == "pop" and lvl == 2 and k % 8 == 7:
                        p = root + 12
                    arr.add("bass", Event(s + x, min(step * 0.9, d - x), p, 0.62 if x == 0 else 0.5))
                    x += step
                    k += 1

        # --- ドラム ---
        if style == "simple":
            continue
        n_bars = sec.bars
        for b in range(n_bars):
            bs = t0 + b * bpb
            last_bar = b == n_bars - 1
            fill = last_bar and nxt is not None and (
                {"low": 0, "mid": 1, "high": 2}.get(nxt.energy, 1) >= lvl and lvl >= 1 or nxt.energy == "high")

            def hit(off, note, vel):
                if off < bpb:
                    arr.add("drums", Event(bs + off, 0.25, note, vel))

            if b == 0 and lvl == 2:
                hit(0, CRASH, 0.7)
            if style == "ballad":
                if lvl == 0:
                    continue
                for q in range(bpb):
                    hit(q, HAT, 0.25)
                hit(0, KICK, 0.7)
                hit(2.5, KICK, 0.5)
                hit(1, STICK if lvl == 1 else SNARE, 0.55)
                hit(3, STICK if lvl == 1 else SNARE, 0.55)
            else:
                if lvl == 0 and style == "pop":
                    if b % 2 == 0:
                        hit(0, KICK, 0.55)
                    for q in range(bpb):
                        hit(q, HAT, 0.22)
                    continue
                for e8 in range(bpb * 2):
                    off = e8 / 2
                    if style == "rock" or lvl == 2:
                        note = OPEN_HAT if (lvl == 2 and e8 % 4 == 3 and style != "rock") else HAT
                        hit(off, note, 0.32 if e8 % 2 == 0 else 0.22)
                    else:
                        hit(off, HAT, 0.28 if e8 % 2 == 0 else 0.18)
                kicks = [0, 2] if lvl == 1 else [0, 1.5, 2, 2.5]
                if style == "rock":
                    kicks = [0, 0.5, 2, 2.5] if lvl else [0, 2]
                for k in kicks:
                    if not (fill and k >= 3):
                        hit(k, KICK, 0.8)
                for sn in range(1, bpb, 2):
                    if not (fill and sn >= 3):
                        hit(sn, SNARE, 0.7)
            if fill:
                for i in range(4):
                    hit(3 + i * 0.25, SNARE if i < 2 else (TOM_H if i == 2 else TOM_L), 0.45 + 0.1 * i)

    arr.total_beats = float(song.total_beats)
    # 最後にジャーンと終わる
    end = arr.total_beats
    last_chord = None
    if timeline:
        lsec = timeline[-1][1]
        if lsec.chords and lsec.chords[-1][2] != "N.C.":
            last_chord = parse_chord(lsec.chords[-1][2])
    if last_chord and song.style != "simple":
        v = _voicing(last_chord.pcs, prev_voice)
        for p in v:
            arr.add("piano", Event(end, 3.0, p, 0.45))
        arr.add("bass", Event(end, 3.0, _bass_note(last_chord.bass), 0.6))
        arr.add("drums", Event(end, 0.25, CRASH, 0.6))
        arr.add("drums", Event(end, 0.25, KICK, 0.7))
        arr.total_beats = end + 4
    return arr
