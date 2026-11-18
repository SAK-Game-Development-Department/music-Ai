"""原曲の歌詞を曲データに入れる。

- YouTube の歌詞字幕（.vtt / .srt）を読む → 時間つきの行。歌詞が出ている小節 = 歌、出ていない小節 = 間奏
- 貼り付けた歌詞（時間なし）→ 歌うパートに、順番どおり・長さ（モーラ数）が合うように並べる。
  歌詞が 1 行も入らなかったパートは間奏（歌わない）にする
"""
from __future__ import annotations

import re
from pathlib import Path

from .lyrics import split_mora
from .reading import to_ruby

# 字幕の中で歌詞ではないもの
_NOISE = re.compile(r"^\s*[\[（(【]?\s*(音楽|拍手|笑|music|Music|MUSIC|歓声|♪+)\s*[\]）)】]?\s*$")
_TAG = re.compile(r"<[^>]+>")
_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[.,](\d{3})|(\d+):(\d\d)[.,](\d{3})")


def _sec(m: re.Match) -> float:
    if m.group(1) is not None:
        h, mi, s, ms = m.group(1), m.group(2), m.group(3), m.group(4)
        return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms) / 1000
    mi, s, ms = m.group(5), m.group(6), m.group(7)
    return int(mi) * 60 + int(s) + int(ms) / 1000


def clean_line(text: str) -> str:
    t = _TAG.sub("", text)
    t = t.replace("&nbsp;", " ").replace("♪", " ").replace("♫", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return "" if _NOISE.match(t) else t


def parse_subtitles(path: str | Path) -> list[tuple[float, float, str]]:
    """.vtt / .srt → [(開始秒, 終了秒, 歌詞の行)]。同じ行が続く（自動字幕の流れ）ものはまとめる。"""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    cues: list[tuple[float, float, str]] = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    for b in blocks:
        lines = b.strip().split("\n")
        for i, ln in enumerate(lines):
            if "-->" in ln:
                times = list(_TIME.finditer(ln))
                if len(times) < 2:
                    break
                start, end = _sec(times[0]), _sec(times[1])
                body = " ".join(clean_line(x) for x in lines[i + 1:])
                body = re.sub(r"\s+", " ", body).strip()
                if body:
                    cues.append((start, end, body))
                break
    # 重なり・くり返しの整理（自動字幕は同じ行が何度も出る）
    out: list[tuple[float, float, str]] = []
    for s, e, t in cues:
        if out and (t == out[-1][2] or out[-1][2].endswith(t)):
            out[-1] = (out[-1][0], max(e, out[-1][1]), out[-1][2])
            continue
        if out and t.startswith(out[-1][2]) and s <= out[-1][1] + 0.05:
            out[-1] = (out[-1][0], e, t)
            continue
        out.append((s, e, t))
    return out


def lyric_lines(text: str) -> list[list[str]]:
    """貼り付けた歌詞 → ブロック（空行で区切る）ごとの行のリスト。字幕っぽい記号は取り除く。"""
    blocks: list[list[str]] = [[]]
    for raw in text.replace("\r\n", "\n").split("\n"):
        ln = clean_line(raw)
        if not ln:
            if blocks[-1]:
                blocks.append([])
            continue
        blocks[-1].append(ln)
    return [b for b in blocks if b]


def mora_of(line: str) -> int:
    try:
        return len([s for s in split_mora(to_ruby(line)) if not s.melisma])
    except ValueError:
        return max(1, len(line))


def assign_lines(parts: list[tuple[str, int, bool]], blocks: list[list[str]],
                 bars: list[int] | None = None) -> dict[str, list[str]]:
    """歌詞の行を、パートに順番どおり割り当てる（時間がわからないとき）。

    parts: [(パート名, 歌う音の数, 歌っていそうか), ...]（曲の順）
    bars: パートごとの小節数（あれば「歌う速さはだいたい一定」として、小節数から入る量を見積もる。
          聴き取った音符の数は伴奏が混ざって不確かなので、こちらを主に使う）
    返り値: {パート名: [行, ...]}（行が 1 つも入らないパートは含めない＝間奏）

    行の並びは変えずに、各パートに続きの何行かを入れる。コストは
      |パートの音の数 − 入れた行のモーラ数の合計| ＋ 歌っていそうなパートを空にする罰 ＋ 間奏らしいパートに入れる罰
      ＋ 空行で分かれたブロックの途中でパートが切り替わる罰
    が最小になる分け方を動的計画法で求める。
    """
    lines = [ln for b in blocks for ln in b]
    block_end = set()
    k = 0
    for b in blocks:
        k += len(b)
        block_end.add(k)  # この行数のところでブロックが終わる
    mora = [mora_of(ln) for ln in lines]
    n, P = len(lines), len(parts)
    # パートごとに入りそうなモーラ数（目安）
    vocal_bars = sum(b for b, (_, _, v) in zip(bars or [], parts) if v) if bars else 0
    if bars and vocal_bars:
        rate = sum(mora) / vocal_bars  # 1 小節あたりのモーラ数
        target = [0.6 * b * rate + 0.4 * notes * (sum(mora) / max(1, sum(x[1] for x in parts if x[2])))
                  if v else b * rate for b, (_, notes, v) in zip(bars, parts)]
    else:
        target = [float(notes) for _, notes, _ in parts]
    INF = float("inf")
    best = [[INF] * (n + 1) for _ in range(P + 1)]
    back = [[0] * (n + 1) for _ in range(P + 1)]
    best[0][0] = 0.0
    prefix = [0]
    for m in mora:
        prefix.append(prefix[-1] + m)
    for p in range(P):
        _, _, vocal = parts[p]
        notes = target[p]
        for i in range(n + 1):
            if best[p][i] == INF:
                continue
            for j in range(i, min(n, i + 12) + 1):  # 1 パートに最大 12 行
                if j == i:
                    cost = notes * 0.8 if vocal else 0.0
                else:
                    cost = abs(notes - (prefix[j] - prefix[i]))
                    if not vocal:
                        cost += notes * 0.8 + 8  # 間奏らしいパートに歌詞を入れるのは、よほど合うときだけ
                    if j not in block_end and j < n:
                        cost += 3  # ブロックの途中で切れる
                c = best[p][i] + cost
                if c < best[p + 1][j]:
                    best[p + 1][j] = c
                    back[p + 1][j] = i
    # 余った行は最後のパートに付ける（すべての行を使う）
    j = n
    if best[P][n] == INF:
        j = max(i for i in range(n + 1) if best[P][i] < INF)
    out: dict[str, list[str]] = {}
    for p in range(P, 0, -1):
        i = back[p][j]
        if j > i:
            out[parts[p - 1][0]] = lines[i:j]
        j = i
    return out
