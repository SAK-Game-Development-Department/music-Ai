"""歌詞のタイミング合わせ: Whisper が聴き取った「言葉と時刻」を使って、
原曲の歌詞の 1 モーラずつが「いつ歌われたか」を決め、その時刻に音符を置いたメロディを作る。

  1. Whisper の言葉ごとの時刻 → モーラごとの時刻（言葉の中は等分）
  2. 原曲の歌詞があるとき（貼り付け・字幕）: 歌詞のモーラ列と、Whisper のモーラ列を突き合わせ
     （かなの一致で対応づけ。聴き間違いの所は前後から補間）→ 歌詞の 1 モーラずつの時刻
     原曲の歌詞がないとき: Whisper の聴き取りをそのまま原曲の歌詞にする
  3. 各モーラの時刻に音符を置く（16 分音符に合わせる）。音の高さは、その時刻の歌メロの高さ（聴き取り）から
  4. 歌詞の出ている小節 = 歌、それ以外 = 間奏。行の途中でパートが切れないように分ける

こうして作ったメロディは「歌詞 1 モーラ = 音符 1 つ」になっているので、
同じ長さの替え歌の歌詞が、原曲と同じタイミングでぴったり乗る。
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np

from .lyrics import split_mora


@dataclass
class TimedLine:
    text: str  # 表示（漢字まじり）
    ruby: str  # 歌詞の書式 {漢字|よみ}
    mora: list[str]  # モーラ（かな）
    times: list[float]  # 各モーラの歌い始め（秒、取り込み範囲の先頭から）
    end: float  # 行の歌い終わり（秒）
    matched: float = 1.0  # Whisper と一致したモーラの割合（原曲の歌詞があるとき）
    meta: dict = field(default_factory=dict)


_KEEP = re.compile(r"[ぁ-ゖァ-ヺー一-龯々〆a-zA-Z0-9]")


def _ruby(text: str) -> str:
    from .reading import ReadingUnavailable, to_ruby

    try:
        return to_ruby(text)
    except ReadingUnavailable:
        return text


def _mora_list(text: str) -> list[str]:
    t = "".join(c if _KEEP.match(c) else " " for c in text)
    try:
        return [s.text for s in split_mora(_ruby(t)) if not s.melisma]
    except ValueError:
        return []


def _norm(m: str) -> str:
    """突き合わせ用に、かなをそろえる（カタカナ→ひらがな、を→お、づ→ず など）。"""
    h = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in m)
    return h.replace("を", "お").replace("づ", "ず").replace("ぢ", "じ").replace("ゐ", "い").replace("ゑ", "え")


def asr_mora(segments) -> list[tuple[str, float, float]]:
    """Whisper の結果 → [(モーラ, 開始, 終了)]。言葉の中では時間を等分する。"""
    out: list[tuple[str, float, float]] = []
    for seg in segments:
        words = seg.words or []
        if not words:
            ms = _mora_list(seg.text)
            if ms:
                step = (seg.end - seg.start) / len(ms)
                out += [(m, seg.start + k * step, seg.start + (k + 1) * step) for k, m in enumerate(ms)]
            continue
        for w in words:
            ms = _mora_list(w.text)
            if not ms:
                continue
            step = max(0.0, (w.end - w.start)) / len(ms)
            out += [(m, w.start + k * step, w.start + (k + 1) * step) for k, m in enumerate(ms)]
    return out


def align_known(lines: list[str], segments) -> list[TimedLine] | None:
    """原曲の歌詞の行に、Whisper の時刻を付ける。ほとんど一致しなければ None。"""
    asr = asr_mora(segments)
    if not asr or not lines:
        return None
    lyr: list[tuple[int, str]] = []  # (行番号, モーラ)
    per_line: list[list[str]] = []
    for li, ln in enumerate(lines):
        ms = _mora_list(ln)
        per_line.append(ms)
        lyr += [(li, m) for m in ms]
    a = [_norm(m) for _, m in lyr]
    b = [_norm(m) for m, _, _ in asr]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    t: list[float | None] = [None] * len(a)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            t[blk.a + k] = asr[blk.b + k][1]
    known = [i for i, x in enumerate(t) if x is not None]
    if len(known) < max(3, 0.15 * len(a)):
        return None
    # 一致しなかったモーラは、前後の一致した時刻から補間（端は 1 モーラ 0.2 秒で外挿）
    for i in range(len(a)):
        if t[i] is not None:
            continue
        prev = max((k for k in known if k < i), default=None)
        nxt = min((k for k in known if k > i), default=None)
        if prev is not None and nxt is not None:
            t[i] = t[prev] + (t[nxt] - t[prev]) * (i - prev) / (nxt - prev)
        elif prev is not None:
            t[i] = t[prev] + 0.2 * (i - prev)
        else:
            t[i] = max(0.0, t[nxt] - 0.2 * (nxt - i))
    # 時刻は増えていく順に（逆転したら少しずらす）
    for i in range(1, len(t)):
        if t[i] <= t[i - 1]:
            t[i] = t[i - 1] + 0.05
    out: list[TimedLine] = []
    i = 0
    matched_set = set(known)
    for li, ln in enumerate(lines):
        n = len(per_line[li])
        if n == 0:
            continue
        times = t[i:i + n]
        nxt_start = t[i + n] if i + n < len(t) else None
        # 行の終わり: 次の行の頭まで（最大 1.2 秒）
        end = times[-1] + 0.5
        if nxt_start is not None:
            end = min(times[-1] + 1.2, nxt_start - 0.05)
        end = max(end, times[-1] + 0.12)
        hit = sum(1 for k in range(i, i + n) if k in matched_set) / n
        out.append(TimedLine(ln, _ruby(ln), per_line[li], [float(x) for x in times], float(end), hit))
        i += n
    return out


def lines_from_asr(segments, max_mora: int = 18) -> list[TimedLine]:
    """原曲の歌詞がないとき: Whisper の聴き取りをそのまま歌詞の行にする（長い行は言葉の切れ目で分ける）。"""
    out: list[TimedLine] = []
    for seg in segments:
        words = [w for w in (seg.words or []) if _mora_list(w.text)]
        if not words:
            continue
        groups = [words]
        while any(sum(len(_mora_list(w.text)) for w in g) > max_mora and len(g) > 1 for g in groups):
            new = []
            for g in groups:
                if sum(len(_mora_list(w.text)) for w in g) > max_mora and len(g) > 1:
                    gaps = [(g[k + 1].start - g[k].end, k) for k in range(len(g) - 1)]
                    k = max(gaps)[1] if max(gaps)[0] > 0.15 else len(g) // 2 - 1
                    new += [g[: k + 1], g[k + 1:]]
                else:
                    new.append(g)
            groups = new
        for g in groups:
            text = "".join(w.text for w in g).strip()
            text = re.sub(r"[\s　]+", " ", text)
            ms, ts = [], []
            for w in g:
                wm = _mora_list(w.text)
                step = max(0.0, w.end - w.start) / len(wm)
                ms += wm
                ts += [w.start + k * step for k in range(len(wm))]
            if len(ms) < 2:
                continue
            for k in range(1, len(ts)):
                if ts[k] <= ts[k - 1]:
                    ts[k] = ts[k - 1] + 0.05
            out.append(TimedLine(text, _ruby(text), ms, [float(x) for x in ts], float(max(g[-1].end, ts[-1] + 0.12))))
    return out


def snap_to_onsets(lines: list[TimedLine], onsets: list[float], window: float = 0.15) -> None:
    """各モーラの時刻を、近く（±window 秒）にある「音の立ち上がり」（歌メロの聴き取りで見つけた音符の頭）に寄せる。

    Whisper の時刻は言葉単位でおおまかなので、音から見つけた音符の頭で細かく合わせる。順番は崩さない。
    """
    if not onsets:
        return
    ons = np.array(sorted(onsets))
    used: set[int] = set()
    prev = -1e9
    for ln in lines:
        for k, t in enumerate(ln.times):
            i = int(np.searchsorted(ons, t))
            best = None
            for j in (i - 1, i, i + 1):
                if 0 <= j < len(ons) and j not in used and abs(ons[j] - t) <= window and ons[j] > prev:
                    if best is None or abs(ons[j] - t) < abs(ons[best] - t):
                        best = j
            if best is not None:
                used.add(best)
                ln.times[k] = float(ons[best])
            if ln.times[k] <= prev:
                ln.times[k] = prev + 0.04
            prev = ln.times[k]


# ---------------------------------------------------------------- 曲データを作る
def build_song(an, title: str, lines: list[TimedLine], section_bars: int = 8) -> dict:
    """解析結果（テンポ・キー・コード・歌メロの高さ）と、時刻つきの歌詞の行から曲 dict を作る。"""
    from .song import Note, melody_to_text
    from .transcribe import FPS, _parts_from_bars

    spb = 60 / an.tempo
    sec16 = spb / 4
    scale = set(an.key.scale_pcs)
    # 音から見つけた音符の頭（秒）に、モーラの時刻を寄せる
    snap_to_onsets(lines, [an.t0 + q * sec16 for q, _, _ in an.notes])
    f0 = an.f0 if an.f0 is not None else np.array([])

    def pitch_at(t0: float, t1: float, prev: int | None) -> int:
        a, b = int(t0 * FPS), max(int(t0 * FPS) + 1, int(t1 * FPS))
        seg = f0[a:b] if len(f0) else np.array([])
        seg = seg[~np.isnan(seg)] if len(seg) else seg
        if not len(seg):  # 近くの歌の高さ（±0.3 秒）
            a2, b2 = max(0, int((t0 - 0.3) * FPS)), int((t1 + 0.3) * FPS)
            seg = f0[a2:b2] if len(f0) else np.array([])
            seg = seg[~np.isnan(seg)] if len(seg) else seg
        if not len(seg):
            return prev if prev is not None else 60 + an.key.tonic
        p = float(np.median(seg))
        pr = int(round(p))
        if pr % 12 not in scale:
            for c in (pr - 1, pr + 1):
                if c % 12 in scale and abs(c - p) < 0.75:
                    pr = c
                    break
        return pr

    # 音符（16 分の位置, 長さ, 高さ, 行番号）
    notes: list[list[int]] = []
    line_span: list[tuple[int, int]] = []  # 行ごとの (最初の音の位置, 最後の音の終わり)
    line_end: dict[int, int] = {}
    prev_q = -1
    prev_p = None
    for li, ln in enumerate(lines):
        first = None
        for k, t in enumerate(ln.times):
            q = round((t - an.t0) / sec16)
            if q <= prev_q:
                q = prev_q + 1
            nxt_t = ln.times[k + 1] if k + 1 < len(ln.times) else ln.end
            p = pitch_at(t, max(t + 0.08, t + 0.7 * (nxt_t - t)), prev_p)
            notes.append([q, 1, p, li])
            prev_q, prev_p = q, p
            if first is None:
                first = q
        if first is None:
            continue
        # 長さ: 同じ行の中は次の音まで（レガート）。行の最後は行の終わりまで（最大 2 拍）
        end_q = max(prev_q + 1, min(prev_q + 8, round((ln.end - an.t0) / sec16)))
        line_span.append((first, end_q))
        line_end[li] = end_q
    for k in range(len(notes)):
        q, _, _, li = notes[k]
        if k + 1 < len(notes) and notes[k + 1][3] == li:
            notes[k][1] = notes[k + 1][0] - q
        else:
            nxt_q = notes[k + 1][0] if k + 1 < len(notes) else line_end[li]
            notes[k][1] = max(1, min(line_end[li], nxt_q) - q)
    notes = [n for n in notes if n[0] >= 0]
    if not notes:
        raise ValueError("歌詞のタイミングがわかりませんでした")
    total_16 = max(n[0] + n[1] for n in notes)
    bars = max(an.bars, -(-total_16 // 16))
    chords = list(an.chords) + [an.chords[-1] if an.chords else "C"] * (bars - len(an.chords))
    # 歌詞の出ている小節 = 歌
    vocal = [False] * bars
    for s, e in line_span:
        for b in range(max(0, s // 16), min(bars, (e - 1) // 16 + 1)):
            vocal[b] = True
    # 行の途中では区切らない: 行がまたいでいる小節の境目
    inside = set()
    for s, e in line_span:
        for b in range(s // 16 + 1, (e - 1) // 16 + 1):
            inside.add(b)
    parts = _parts_from_bars(vocal, section_bars)
    parts = _respect_lines(parts, inside, bars)

    sections: dict = {}
    structure: list[str] = []
    n_sung = n_inter = 0
    line_first = {}
    for n in notes:
        line_first.setdefault(n[3], n[0])
    ref_notes = sorted(an.notes)
    for pi, (b0, b1, sung) in enumerate(parts):
        lo, hi = b0 * 16, b1 * 16
        src = [(q, d, p) for q, d, p, _ in notes] if sung else ref_notes
        seq: list = []
        pos = lo
        for a, d, p in src:
            e = a + d
            if a < lo or a >= hi:
                continue
            e2 = min(e, hi)
            if a > pos:
                seq.append(Note(None, Fraction(a - pos, 4)))
            seq.append(Note(p, Fraction(e2 - a, 4)))
            pos = e2
        if pos < hi:
            seq.append(Note(None, Fraction(hi - pos, 4)))
        if sung:
            n_sung += 1
            name = f"パート{n_sung}"
        elif pi == 0:
            name = "イントロ"
        elif pi == len(parts) - 1:
            name = "アウトロ"
        else:
            n_inter += 1
            name = f"間奏{n_inter}"
        sec = {"chords": " | ".join(chords[b0:b1])}
        if any(not x.is_rest for x in seq):
            sec["melody"] = melody_to_text(seq, 4, an.key.prefer_flat)
        if sung:
            mine = [li for li, q in sorted(line_first.items(), key=lambda kv: kv[1]) if lo <= q < hi]
            if mine:
                sec["lyrics"] = "\n".join(lines[li].ruby for li in mine)
                n_notes = sum(1 for x in seq if not x.is_rest)
                if n_notes != sum(len(lines[li].mora) for li in mine):
                    sec["fit"] = True  # 万一ずれたときは歌詞に合わせて調整
        else:
            sec["sing"] = False
        sections[name] = sec
        structure.append(name)
    return {"title": title, "key": an.key.name(), "tempo": an.tempo, "time": "4/4", "style": "pop",
            "structure": structure, "sections": sections}


def _respect_lines(parts: list[tuple[int, int, bool]], inside: set[int], bars: int) -> list[tuple[int, int, bool]]:
    """パートの境目が行の途中（inside）に来ないように、近くの境目へずらす（同じ「歌」の区間の中だけ）。"""
    out = [list(p) for p in parts]
    for k in range(len(out) - 1):
        b = out[k][1]
        if b not in inside or not (out[k][2] and out[k + 1][2]):
            continue
        for d in (1, -1, 2, -2, 3, -3, 4, -4):
            nb = b + d
            if out[k][0] < nb < out[k + 1][1] and nb not in inside:
                out[k][1] = nb
                out[k + 1][0] = nb
                break
    return [tuple(p) for p in out if p[1] > p[0]]
