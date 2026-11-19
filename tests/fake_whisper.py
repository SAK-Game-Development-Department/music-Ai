"""正解のタイミングから Whisper 風の結果を作る（ずれ・聴き間違い・抜けあり）。"""
import random

from musicai.asr import Segment, Word
from musicai.song import load_song
from musicai.reading import segments as rsegs

def truth(song):
    """[(行テキスト(かな), [各モーラの秒])]"""
    out = []
    for st, sec in song.timeline():
        t = float(st) * 60 / song.tempo
        if not sec.lyrics_text: continue
        cur = None; line_idx = None
        for n in sec.notes:
            d = float(n.dur) * 60 / song.tempo
            if not n.is_rest and n.lyric and not n.lyric.melisma:
                if n.lyric.phrase != line_idx:
                    cur = []; out.append(cur); line_idx = n.lyric.phrase
                cur.append(t)
            t += d
    return out

def fake(song, kanji_lines, seed=0, jitter=0.1, err=0.15, drop=0.08):
    rng = random.Random(seed)
    tl = truth(song)
    segs = []
    for line, times in zip(kanji_lines, tl):
        words = []
        k = 0
        from musicai.lyricsync import _mora_list
        for orig, yomi in rsegs(line):
            m = len(_mora_list(orig))
            if m == 0: continue
            ts = times[k:k + m]; k += m
            if not ts: break
            if rng.random() < drop: continue
            text = orig
            if rng.random() < err:  # 聴き間違い（別のかなに）
                text = ''.join(rng.choice('かきくけこさしすせそ') for _ in range(m))
            s = ts[0] + rng.uniform(-jitter, jitter)
            e = (times[k] if k < len(times) else ts[-1] + 0.4) + rng.uniform(-jitter, jitter)
            words.append(Word(s, max(s + 0.05, e), text))
        if words:
            segs.append(Segment(words[0].start, words[-1].end, ''.join(w.text for w in words), words))
    return segs, tl
