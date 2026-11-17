"""歌詞 → モーラ（音符 1 つに乗る単位）への分割。

書き方:
  - ひらがな / カタカナ: 自動でモーラ分割（きょ・う / が・っ・こ・う）
  - 漢字: {漢字|よみ} のようにルビで読みを書く（例: {空|そら}）
  - 英語: 単語ごと。音節は - で区切る（例: twin-kle）
  - ~ または 〜 : メリスマ（前の音を伸ばしたまま次の音符へ）
  - / または改行: フレーズ（息継ぎ）の区切り
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SMALL = set("ゃゅょぁぃぅぇぉゎ")
MELISMA = {"~", "〜", "～"}
PHRASE_BREAKS = {"/", "\n", "／"}
IGNORE = set(" \t　、。，．,.!！?？「」『』（）()・…♪☆★\"'")

_VOWEL_ROWS = {
    "a": "あかがさざただなはばぱまやらわ",
    "i": "いきぎしじちぢにひびぴみりゐ",
    "u": "うくぐすずつづぬふぶぷむゆるゔ",
    "e": "えけげせぜてでねへべぺめれゑ",
    "o": "おこごそぞとどのほぼぽもよろを",
}
VOWEL_OF = {ch: v for v, chars in _VOWEL_ROWS.items() for ch in chars}
VOWEL_OF.update({"ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
                 "ゃ": "a", "ゅ": "u", "ょ": "o", "ゎ": "a"})


def kata_to_hira(text: str) -> str:
    out = []
    for ch in text:
        c = ord(ch)
        if 0x30A1 <= c <= 0x30F6:
            out.append(chr(c - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def is_kana(ch: str) -> bool:
    c = ord(ch)
    return 0x3041 <= c <= 0x3096 or 0x30A1 <= c <= 0x30FA or ch == "ー"


def is_kanji(ch: str) -> bool:
    c = ord(ch)
    return 0x4E00 <= c <= 0x9FFF or 0x3400 <= c <= 0x4DBF or ch in "々〆"


@dataclass
class Syllable:
    text: str  # 表示用（かなのモーラ、英語音節、または "~"）
    phrase: int  # 何番目のフレーズか
    melisma: bool = False

    @property
    def vowel(self) -> str:
        """合成音声用の母音（a i u e o / n / q=促音 / -=前を継続）。"""
        if self.melisma:
            return "-"
        h = kata_to_hira(self.text)
        if not h:
            return "a"
        last = h[-1]
        if last == "ん":
            return "n"
        if last == "っ":
            return "q"
        if last == "ー":
            return "-"
        if last in VOWEL_OF:
            return VOWEL_OF[last]
        # 英語など: 最初に出てくる母音字
        for ch in h.lower():
            if ch in "aiueo":
                return {"a": "a", "i": "i", "u": "u", "e": "e", "o": "o"}[ch]
            if ch == "y":
                return "i"
        return "a"


class LyricError(ValueError):
    pass


def split_mora(text: str) -> list[Syllable]:
    """歌詞文字列を Syllable のリストに分割する。"""
    syl: list[Syllable] = []
    phrase = 0
    i = 0
    n = len(text)
    bad_kanji: list[str] = []

    def add(t: str, melisma: bool = False):
        syl.append(Syllable(t, phrase, melisma))

    while i < n:
        ch = text[i]
        if ch in PHRASE_BREAKS:
            if syl and syl[-1].phrase == phrase:
                phrase += 1
            i += 1
            continue
        if ch in IGNORE:
            i += 1
            continue
        if ch in MELISMA:
            add("~", True)
            i += 1
            continue
        if ch == "{":
            j = text.find("}", i)
            if j < 0 or "|" not in text[i:j]:
                raise LyricError(f"ルビの書き方が違います（{{漢字|よみ}} の形で）: {text[i:i+20]!r}")
            reading = text[i + 1:j].split("|", 1)[1]
            for s in split_mora(reading):
                add(s.text, s.melisma)
            i = j + 1
            continue
        if is_kana(ch):
            j = i + 1
            while j < n and kata_to_hira(text[j]) in SMALL:
                j += 1
            add(text[i:j])
            i = j
            continue
        if ch.isascii() and (ch.isalpha() or ch == "'"):
            j = i
            while j < n and text[j].isascii() and (text[j].isalpha() or text[j] in "'-"):
                j += 1
            word = text[i:j]
            for part in word.split("-"):
                if part:
                    add(part)
            i = j
            continue
        if is_kanji(ch):
            bad_kanji.append(ch)
            i += 1
            continue
        if ch.isdigit():
            raise LyricError(f"数字はよみをかなで書いてください: {ch!r}")
        # その他の記号は無視
        i += 1

    if bad_kanji:
        raise LyricError(
            "漢字はモーラ数が決められないので、{漢字|よみ} で読みを書くか、ひらがなで書いてください: "
            + "".join(dict.fromkeys(bad_kanji))
        )
    # フレーズ番号を詰める
    remap: dict[int, int] = {}
    for s in syl:
        remap.setdefault(s.phrase, len(remap))
        s.phrase = remap[s.phrase]
    return syl


def count_mora(text: str) -> int:
    return sum(1 for s in split_mora(text) if not s.melisma)


def phrases(syls: list[Syllable]) -> list[list[Syllable]]:
    out: list[list[Syllable]] = []
    for s in syls:
        while len(out) <= s.phrase:
            out.append([])
        out[s.phrase].append(s)
    return out


def display_lyrics(text: str) -> list[str]:
    """歌詞カード用: ルビ記法を 漢字(よみ) → 漢字 に戻し、フレーズごとの行にする。"""
    t = re.sub(r"\{([^|}]*)\|[^}]*\}", r"\1", text)
    lines = []
    for line in re.split(r"[\n/／]", t):
        line = line.replace("~", "").replace("〜", "").strip()
        if line:
            lines.append(line)
    return lines
