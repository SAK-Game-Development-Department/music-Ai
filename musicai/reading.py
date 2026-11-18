"""漢字まじりの歌詞 → 読み（かな）。原曲の歌詞をモーラで数えるために使う。

pykakasi（オフラインで動く読み変換）を使い、歌詞でよく出る言葉の読み間違い
（君→くん、今日は→こんにちは など）は ① の表で直す。
結果は歌詞の書式 {漢字|よみ} にするので、画面では漢字のまま表示され、読みが違えば手で直せる。
"""
from __future__ import annotations

import re

# 歌詞でよく使う読み（pykakasi の読みより優先）
LYRIC_READINGS = {
    "君": "きみ", "僕": "ぼく", "僕ら": "ぼくら", "僕たち": "ぼくたち", "君ら": "きみら", "私": "わたし",
    "今日": "きょう", "明日": "あした", "昨日": "きのう", "今": "いま", "名": "な", "名前": "なまえ",
    "空": "そら", "心": "こころ", "夢": "ゆめ", "涙": "なみだ", "未来": "みらい", "愛": "あい",
    "二人": "ふたり", "一人": "ひとり", "時": "とき", "声": "こえ", "光": "ひかり", "世界": "せかい",
    "星": "ほし", "風": "かぜ", "花": "はな", "手": "て", "何": "なに", "日": "ひ", "夜": "よる",
    "朝": "あさ", "雨": "あめ", "海": "うみ", "道": "みち", "胸": "むね", "瞳": "ひとみ", "笑顔": "えがお",
    "想い": "おもい", "思い": "おもい", "季節": "きせつ", "永遠": "えいえん", "奇跡": "きせき",
    "約束": "やくそく", "言葉": "ことば", "場所": "ばしょ", "明日へ": "あしたへ", "此処": "ここ",
    "何処": "どこ", "誰": "だれ", "貴方": "あなた", "貴女": "あなた", "温もり": "ぬくもり",
    # 動詞の語幹（歌詞ではこちらの読みが多い）
    "開け": "あけ", "開く": "ひらく", "生き": "いき", "行こ": "いこ", "行く": "ゆく", "上げ": "あげ",
}

_SUFFIXES = {"は", "が", "を", "に", "の", "へ", "と", "も", "で", "や", "よ", "ね", "ら", "たち", "から", "まで", "だけ"}
_KANJI = re.compile(r"[㐀-䶿一-鿿々〆]")


class ReadingUnavailable(RuntimeError):
    pass


_kks = None


def _kakasi():
    global _kks
    if _kks is None:
        try:
            import pykakasi
        except ImportError:
            raise ReadingUnavailable("漢字の読みを調べる pykakasi が入っていません（pip install pykakasi）。"
                                     "歌詞をひらがなで貼り付けると使えます")
        _kks = pykakasi.kakasi()
    return _kks


def _hira(text: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


def segments(text: str) -> list[tuple[str, str]]:
    """[(表記, よみ), ...]。漢字を含まない部分はそのまま（よみ = 表記）。"""
    if not _KANJI.search(text):
        return [(text, text)]
    out: list[tuple[str, str]] = []
    for seg in _kakasi().convert(text):
        orig, hira = seg["orig"], seg["hira"]
        if not _KANJI.search(orig):
            out.append((orig, orig))
            continue
        # よく使う言葉の読みを優先（「今日は」のように後ろにかながつくものも）
        # （後ろに付いてよいのは助詞などだけ。「光る」の「光」は「ひかり」にしない）
        fixed = None
        for word in sorted(LYRIC_READINGS, key=len, reverse=True):
            rest = orig[len(word):]
            if orig.startswith(word) and (rest == "" or rest in _SUFFIXES):
                fixed = LYRIC_READINGS[word] + rest
                break
        out.append((orig, fixed or hira))
    return out


def to_ruby(text: str) -> str:
    """歌詞の書式に: 『夜空に光る』→『{夜空|よぞら}に{光|ひか}る』。漢字のないところはそのまま。"""
    parts = []
    for orig, yomi in segments(text):
        if _KANJI.search(orig):
            # 送りがな（後ろのかな）はルビの外に出す
            m = re.match(r"^(.*?[㐀-䶿一-鿿々〆])([ぁ-ゖー]*)$", orig)
            if m and m.group(2) and yomi.endswith(m.group(2)):
                parts.append(f"{{{m.group(1)}|{yomi[: len(yomi) - len(m.group(2))]}}}{m.group(2)}")
            else:
                parts.append(f"{{{orig}|{yomi}}}")
        else:
            parts.append(orig)
    return "".join(parts)


def to_kana(text: str) -> str:
    return "".join(y for _, y in segments(text))


def words(text: str) -> list[str]:
    """言葉の区切り（よみ）。くり返し出てくる「決めの言葉」を見つけるのに使う。"""
    return [y for _, y in segments(text) if y.strip()]
