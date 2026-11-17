"""歌詞とコード進行からメロディを作る（0 から作曲）。

docs/01_音楽の作り方.md の「メロディの作り方」をそのままルール化している:
  - 1 モーラ = 1 音符。8 分音符が基本、入りきらなければ 16 分
  - フレーズ末は長い音 + 休符（息継ぎ）
  - 強拍・長い音はコードトーン、弱拍は音階の音で順次進行
  - フレーズは山なり。サビは音域を高く
  - 同じモーラ数のフレーズはリズムを再利用、1 つおきのフレーズは旋律も再利用（覚えやすさ）
  - 最後のフレーズは主音で終止

作曲仕様（spec）YAML の例は specs/ を参照。出力は song YAML（自由に手で直せる）。
"""
from __future__ import annotations

import math
import random
from fractions import Fraction

from .lyrics import phrases, split_mora
from .song import Note, SongError, default_energy, melody_to_text, parse_chords, save_song_dict
from .theory import Key, parse_chord, parse_key, progression_to_chords, scale_pitches

REGISTERS = {
    "low": (57, 72),   # A3〜C5
    "mid": (60, 76),   # C4〜E5
    "high": (64, 79),  # E4〜G5
}


def _register_for(name: str, energy: str, spec: dict) -> tuple[int, int]:
    reg = spec.get("register") or {"low": "low", "mid": "mid", "high": "high"}[energy]
    lo, hi = REGISTERS[reg]
    shift = int(spec.get("transpose_range", 0))
    return lo + shift, hi + shift


def _rhythm(n: int, bars: int, bpb: int, rng: random.Random, style: str) -> tuple[list[Fraction], Fraction, Fraction] | None:
    """n モーラを bars 小節に置くリズム。返り値 (音符長リスト, 頭の休符, 末尾の休符)。"""
    for unit in (Fraction(1, 2), Fraction(1, 4)):
        slots_total = int(bars * bpb / unit)
        rest_end = int(1 / unit)  # 最低 1 拍の息継ぎ
        offsets = [0, int(Fraction(1, 2) / unit), int(1 / unit)] if unit == Fraction(1, 2) else [0, 1, 2]
        rng.shuffle(offsets)
        for off in offsets + [0]:
            avail = slots_total - off - rest_end
            if avail >= n:
                break
        else:
            continue
        if avail < n:
            continue
        durs = [1] * n
        extra = avail - n
        # フレーズ末を伸ばす
        end_len = min(extra, int(2 / unit) if style == "ballad" else int(Fraction(3, 2) / unit))
        durs[-1] += end_len
        extra -= end_len
        # 拍頭の音を伸ばして 4 分音符に（余りがある分だけ）
        pos = off
        starts = []
        for d in durs:
            starts.append(pos)
            pos += d
        order = list(range(n - 1))
        rng.shuffle(order)
        order.sort(key=lambda i: (starts[i] * unit) % 1 != 0)  # 拍頭を優先
        for i in order:
            if extra <= 0:
                break
            if (starts[i] * unit) % 1 == 0:
                durs[i] += 1
                extra -= 1
                # 後ろの開始位置をずらす
                for j in range(i + 1, n):
                    starts[j] += 1
        rest_after = rest_end + extra
        return [d * unit for d in durs], off * unit, rest_after * unit
    return None


def _chord_at(chords, t: Fraction):
    for s, d, nm in chords:
        if s <= t < s + d:
            return nm
    return chords[-1][2]


def _choose(cands, target, prev, rng, leap_w=1.0):
    best = None
    for c in cands:
        cost = abs(c - target) * 0.6
        if prev is not None:
            iv = abs(c - prev)
            cost += (0 if iv <= 2 else (iv - 2) * 0.9) * leap_w
            if iv == 0:
                cost += 0.8
            if iv in (6, 10, 11) or iv > 9:
                cost += 6
        cost += rng.random() * 1.2
        if best is None or cost < best[0]:
            best = (cost, c)
    return best[1]


def _pitches_for(starts, durs, chords, key: Key, lo, hi, prev, rng, peak, is_final, bpb):
    scale = scale_pitches(key, lo, hi)
    n = len(durs)
    out = []
    center = (lo + hi) / 2
    for i, (t, d) in enumerate(zip(starts, durs)):
        ch = parse_chord(_chord_at(chords, t))
        chord_tones = [p for p in scale_pitches(key, lo, hi) if p % 12 in ch.pcs] or \
                      [p for p in range(lo, hi + 1) if p % 12 in ch.pcs]
        strong = (t % 1 == 0 and (t % bpb) % 2 == 0) or d >= 1 or i == n - 1
        pos = i / max(1, n - 1)
        # 山なりの目標
        arc = math.sin(math.pi * min(1.0, pos * 1.15)) if n > 2 else 0.5
        target = center - 4 + (peak - center + 4) * arc
        if i == n - 1:
            target = center - 2 if not is_final else center - 3
        cands = chord_tones if strong else [p for p in scale if prev is None or abs(p - prev) <= 4] or scale
        if i == n - 1 and is_final:
            tonics = [p for p in chord_tones if p % 12 == key.tonic]
            if tonics:
                cands = tonics
        p = _choose(cands, target, prev, rng)
        out.append(p)
        prev = p
    return out


def compose_section(name: str, spec: dict, key: Key, bpb: int, style: str, rng: random.Random,
                    prev_pitch=None, is_last_vocal=False):
    energy = spec.get("energy", default_energy(name))
    chords_txt = spec.get("chords")
    if not chords_txt:
        prog = spec.get("progression", "I V vi IV")
        chord_list = progression_to_chords(prog, key)
    else:
        chord_list = None
    lyrics = spec.get("lyrics", "") or ""
    syls = split_mora(lyrics) if lyrics else []
    lyr_phr = phrases(syls)
    phrase_bars = int(spec.get("phrase_bars", 2))

    # 各フレーズに必要な小節数を決める
    plan = []
    for p in lyr_phr:
        n = len(p)
        b = phrase_bars
        while n > b * bpb * 2 - 2 and b < 8:  # 8 分音符で入りきらなければ小節を倍に
            b *= 2
        plan.append((n, b))
    lyric_bars = sum(b for _, b in plan)
    bars = int(spec.get("bars", 0)) or lyric_bars or 4
    if lyric_bars and bars < lyric_bars:
        bars = lyric_bars
    if chord_list is not None:
        # 進行を小節数ぶん繰り返す（1 コード = 1 小節。chords_per_bar で 2 にも）
        cpb = int(spec.get("chords_per_bar", 1))
        seq = []
        while len(seq) < bars * cpb:
            seq.extend(chord_list)
        seq = seq[: bars * cpb]
        bar_txt = []
        for b in range(bars):
            bar_txt.append(" ".join(seq[b * cpb:(b + 1) * cpb]))
        chords_txt = " | ".join(bar_txt)
    chords = parse_chords(chords_txt, key, bpb)
    total = chords[-1][0] + chords[-1][1]
    bars = int(total // bpb)

    notes: list[Note] = []
    lo, hi = _register_for(name, energy, spec)
    peak = hi - 2 if energy == "high" else (lo + hi) / 2 + 3
    t = Fraction(0)
    rhythm_cache: dict[int, tuple] = {}
    pitch_hist: list[list[int]] = []
    for pi, (n, b) in enumerate(plan):
        if n in rhythm_cache and rhythm_cache[n][3] == b:
            durs, head, tail, _ = rhythm_cache[n]
        else:
            r = _rhythm(n, b, bpb, rng, style)
            if r is None:
                raise SongError(f"[{name}] フレーズ{pi + 1} の歌詞が長すぎます（{n} モーラ）。/ で分けてください")
            durs, head, tail = r
            rhythm_cache[n] = (durs, head, tail, b)
        starts = []
        pos = t + head
        for d in durs:
            starts.append(pos)
            pos += d
        is_final = is_last_vocal and pi == len(plan) - 1 or (pi == len(plan) - 1 and energy == "high")
        # 旋律の再利用: 2 つ前のフレーズと同じ長さなら、最後 2 音以外コピー
        reuse = None
        if pi >= 2 and len(pitch_hist[pi - 2]) == n and pi % 2 == 0:
            reuse = pitch_hist[pi - 2]
        p_peak = peak + (2 if pi == len(plan) - 1 and energy == "high" else 0) - (2 if pi % 2 == 0 else 0)
        pitches = _pitches_for(starts, durs, chords, key, lo, hi, prev_pitch, rng, p_peak, is_final, bpb)
        if reuse:
            keep = max(0, n - 2)
            pitches = reuse[:keep] + pitches[keep:]
            # 強拍でコードに合わない音はコードトーンに寄せる
            for k in range(keep):
                ch = parse_chord(_chord_at(chords, starts[k]))
                if starts[k] % 2 == 0 and pitches[k] % 12 not in ch.pcs:
                    near = min((p for p in range(lo, hi + 1) if p % 12 in ch.pcs), key=lambda p: abs(p - pitches[k]))
                    pitches[k] = near
        pitch_hist.append(pitches)
        if head:
            notes.append(Note(None, head))
        for p, d in zip(pitches, durs):
            notes.append(Note(p, d))
        prev_pitch = pitches[-1]
        t += b * bpb
        if tail:
            notes.append(Note(None, tail))
    used = sum((nn.dur for nn in notes), Fraction(0))
    if used < total:
        notes.append(Note(None, total - used))
    # 休符を連結
    merged: list[Note] = []
    for nn in notes:
        if merged and nn.is_rest and merged[-1].is_rest:
            merged[-1] = Note(None, merged[-1].dur + nn.dur)
        else:
            merged.append(nn)
    out = {"chords": chords_txt}
    if any(not nn.is_rest for nn in merged):
        out["melody"] = melody_to_text(merged, bpb, key.prefer_flat)
    if lyrics:
        out["lyrics"] = lyrics
    if "energy" in spec:
        out["energy"] = spec["energy"]
    return out, prev_pitch


def compose(spec: dict) -> dict:
    """作曲仕様 → song dict。"""
    key = parse_key(str(spec.get("key", "C major")))
    bpb = int(str(spec.get("time", "4/4")).split("/")[0])
    style = spec.get("style", "pop")
    rng = random.Random(spec.get("seed", 0))
    secs = spec.get("sections") or {}
    structure = spec.get("structure") or list(secs)
    out_secs: dict = {}
    prev = None
    vocal_names = [s for s in structure if (secs.get(s) or {}).get("lyrics")]
    last_vocal = vocal_names[-1] if vocal_names else None
    for name in dict.fromkeys(structure):
        sspec = dict(secs.get(name) or {})
        if "base" in sspec:
            base = {k: v for k, v in sspec.items()}
            out_secs[name] = {**base, "fit": True}
            continue
        sec, prev = compose_section(name, sspec, key, bpb, style, rng, prev, name == last_vocal)
        out_secs[name] = sec
    return {
        "title": spec.get("title", "untitled"),
        "key": key.name(),
        "tempo": spec.get("tempo", 120),
        "time": f"{bpb}/4",
        "style": style,
        "structure": list(structure),
        "sections": out_secs,
    }


def compose_file(spec_path: str, out_path: str) -> dict:
    import yaml
    from pathlib import Path

    spec = yaml.safe_load(Path(spec_path).read_text(encoding="utf-8"))
    song = compose(spec)
    header = {"_note": "musicai compose で自動生成。melody / chords は自由に書き換えてOK"}
    save_song_dict({**header, **song}, out_path)
    return song
