"""替え歌: メロディはそのままに歌詞を差し替え、モーラ数のズレを自動調整する。

調整ルール（docs/02_替え歌の作り方.md 参照）
  歌詞が多い → いちばん長い音符を半分に割る（同じ高さで連打）。フレーズ末の音はなるべく残す
  歌詞が少ない → ① 同じ高さで隣り合う音符をつなげる（タイ）
                 ② それでも余る音符はメリスマ（前の文字を伸ばしたまま音程だけ変える）
  フレーズ（休符で区切られたまとまり）と歌詞の / や改行の数が一致すれば、フレーズ単位で合わせる
"""
from __future__ import annotations

from fractions import Fraction

from .lyrics import Syllable, phrases, split_mora
from .song import Note, attach_lyrics

MIN_DUR = Fraction(1, 4)


BREATH = Fraction(1)  # これ以上の休符をフレーズ（息継ぎ）の区切りとみなす


def melody_phrases(notes: list[Note], want: int | None = None) -> list[list[int]]:
    """休符で区切られたフレーズ（音符のインデックスのまとまり）。

    1 拍未満の短い休符はフレーズの中の「間」として、まとまりに含める（インデックスも含む）。
    want（歌詞のフレーズ数）が休符による区切りより多いときは、
    長い音符（1.5 拍以上）の後ろでも区切る（長い順に）。
    """
    groups: list[list[int]] = []
    cur: list[int] = []
    pending: list[int] = []  # 短い休符（次に音が来たらまとまりに入れる）
    for i, n in enumerate(notes):
        if n.is_rest:
            if cur and n.dur < BREATH:
                pending.append(i)
            elif cur:
                groups.append(cur)
                cur, pending = [], []
        else:
            cur.extend(pending)
            pending = []
            cur.append(i)
    if cur:
        groups.append(cur)
    if want and want > len(groups):
        cands = [(notes[g[k]].dur, -g[k], gi, k) for gi, g in enumerate(groups)
                 for k in range(len(g) - 1) if not notes[g[k]].is_rest and notes[g[k]].dur >= Fraction(3, 2)]
        cands.sort(reverse=True)
        need = want - len(groups)
        if len(cands) >= need:
            cut = {(gi, k) for _, _, gi, k in cands[:need]}
            new = []
            for gi, g in enumerate(groups):
                part = []
                for k, idx in enumerate(g):
                    part.append(idx)
                    if (gi, k) in cut:
                        new.append(part)
                        part = []
                if part:
                    new.append(part)
            groups = new
    return groups


SMALL_PHRASE = 3  # この数以下の音しかないフレーズは、となりのフレーズとまとめる（聴き取りの細切れ対策）


def merge_small_phrases(notes: list[Note], groups: list[list[int]], small: int = SMALL_PHRASE) -> list[list[int]]:
    """歌う音が small 個以下のフレーズを、近い方のとなりのフレーズとまとめる（間の休符も含める）。"""
    def sung(g):
        return sum(1 for i in g if not notes[i].is_rest and not notes[i].melisma)

    groups = [list(g) for g in groups]
    while len(groups) > 1:
        idx = next((k for k, g in enumerate(groups) if sung(g) <= small), None)
        if idx is None:
            break
        gap_prev = (groups[idx][0] - groups[idx - 1][-1]) if idx > 0 else None
        gap_next = (groups[idx + 1][0] - groups[idx][-1]) if idx + 1 < len(groups) else None
        if gap_next is None or (gap_prev is not None and gap_prev <= gap_next):
            a, b = idx - 1, idx
        else:
            a, b = idx, idx + 1
        groups[a] = list(range(groups[a][0], groups[b][-1] + 1))  # 間の休符もまとまりに入れる
        del groups[b]
    return groups


def _slots(group: list[Note]) -> int:
    return sum(1 for n in group if not n.is_rest and not n.melisma)


def fit_group(group: list[Note], target: int) -> tuple[list[Note], list[str]]:
    """歌う音符のまとまり group を、target 個の歌詞が乗るように変形する。"""
    g = [Note(n.pitch, n.dur, None, n.melisma) for n in group]
    log: list[str] = []
    # 既存のメリスマを先に解除して使う
    while _slots(g) < target and any(n.melisma for n in g):
        for n in g:
            if n.melisma:
                n.melisma = False
                break
    split = 0
    while _slots(g) < target:
        cands = [i for i, n in enumerate(g) if not n.is_rest and n.dur / 2 >= MIN_DUR]
        if not cands:
            log.append(f"⚠ 音符が短すぎてこれ以上分割できません（あと {target - _slots(g)} モーラ多い）")
            break
        last = max(i for i, n in enumerate(g) if not n.is_rest)

        def score(i):
            w = g[i].dur
            if i == last and len(g) > 1:
                w *= Fraction(1, 2)  # フレーズ末の伸ばしは残したい
            return (w, -i)

        i = max(cands, key=score)
        n = g[i]
        a = n.dur / 2
        if n.dur == Fraction(3, 2) or n.dur == Fraction(3):
            a = n.dur * 2 / 3
        a = max(MIN_DUR, Fraction(round(a * 4), 4)) if a >= MIN_DUR else a
        b = n.dur - a
        g[i:i + 1] = [Note(n.pitch, a, None, n.melisma), Note(n.pitch, b, None, False)]
        split += 1
    tied = 0
    melis = 0
    while _slots(g) > target:
        # ① 同じ高さの隣り合う音をタイでつなぐ（短い組から）
        pairs = [i for i in range(len(g) - 1) if not g[i].is_rest and g[i].pitch == g[i + 1].pitch
                 and not g[i + 1].melisma]
        if pairs:
            i = min(pairs, key=lambda i: (g[i].dur + g[i + 1].dur, -i))
            g[i:i + 2] = [Note(g[i].pitch, g[i].dur + g[i + 1].dur, None, g[i].melisma)]
            tied += 1
            continue
        # ② メリスマ: 先頭以外で、前の音との音程が近く短い音を選ぶ（フレーズ末寄り優先）
        # 直前が休符の音はメリスマにできない（伸ばす文字がない）
        cands = [i for i in range(1, len(g)) if not g[i].is_rest and not g[i].melisma and not g[i - 1].is_rest]
        if not cands:
            log.append(f"⚠ 歌詞が少なすぎて合わせきれません（あと {_slots(g) - target} モーラ足りない）")
            break
        i = min(cands, key=lambda i: (abs(g[i].pitch - g[i - 1].pitch) > 2, g[i].dur, -i))
        g[i].melisma = True
        melis += 1
    if split:
        log.append(f"音符を {split} 回分割")
    if tied:
        log.append(f"同じ高さの音を {tied} 回つなげた")
    if melis:
        log.append(f"{melis} 音をメリスマ（伸ばし）に")
    return g, log


def fit_lyrics(notes: list[Note], lyrics: str) -> tuple[list[Note], list[str]]:
    """notes（休符含む）に lyrics をフィットさせた新しい Note リストとレポートを返す。"""
    syls = split_mora(lyrics)
    lyr_phr = phrases(syls)
    raw_phr = melody_phrases(notes, len(lyr_phr))
    merged_phr = merge_small_phrases(notes, raw_phr)
    # 歌詞の行数と合う方の区切りを使う（ふつうは細切れをまとめた方）
    mel_phr = raw_phr if len(raw_phr) == len(lyr_phr) and len(merged_phr) != len(lyr_phr) else merged_phr
    report: list[str] = []
    total_slots = sum(1 for n in notes if not n.is_rest and not n.melisma)
    report.append(f"元のメロディ: 歌う音 {total_slots} 個 / {len(mel_phr)} フレーズ")
    report.append(f"新しい歌詞: {len(syls)} モーラ / {len(lyr_phr)} フレーズ")

    if len(lyr_phr) == len(mel_phr) and len(mel_phr) > 1:
        targets = [len(p) for p in lyr_phr]
        report.append("→ フレーズごとに合わせます")
    else:
        if len(lyr_phr) > 1:
            report.append(
                f"→ フレーズ数が違う（メロディ {len(mel_phr)} / 歌詞 {len(lyr_phr)}）ので全体で配分します。"
                " 歌詞を / で区切ってフレーズ数を揃えると自然になります"
            )
        # 各メロディフレーズの元の音数に比例して配分
        sizes = [_slots([notes[i] for i in grp]) for grp in mel_phr]
        total = sum(sizes) or 1
        n = len(syls)
        targets = [max(1, round(n * s / total)) for s in sizes]
        while sum(targets) > n:
            targets[targets.index(max(targets))] -= 1
        while sum(targets) < n:
            targets[targets.index(min(targets))] += 1

    out: list[Note] = []
    gi = 0
    i = 0
    while i < len(notes):
        if notes[i].is_rest:
            out.append(Note(None, notes[i].dur))
            i += 1
            continue
        grp = mel_phr[gi]
        new, log = fit_group([notes[j] for j in grp], targets[gi])
        orig = _slots([notes[j] for j in grp])
        mark = "✓" if orig == targets[gi] else "△"
        report.append(f"  {mark} フレーズ{gi + 1}: {orig}音 ← {targets[gi]}モーラ  {'、'.join(log)}")
        if any(l.startswith("⚠") for l in log):
            report.append("⚠ " + "、".join(l for l in log if l.startswith("⚠")))
        out.extend(new)
        i = grp[-1] + 1
        gi += 1
    attach_lyrics(out, lyrics, "kaeuta")
    return out, report
