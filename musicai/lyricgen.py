"""歌詞の自動生成（オフライン・ルールベース）。

替え歌で「フレーズごとの音の数」がわかっているとき、ちょうどその数のモーラになる歌詞を作る。

しくみ:
  - テーマ別・場面別（起・承・転・結）に、自然に読める短い言葉のかたまり（フレーズ片）を用意
  - 1 行 = 目標モーラ数ちょうどになるよう、フレーズ片を 1〜3 個つなぐ（足りない分は「ねえ」「よ」などの合いの手で埋める）
  - ストーリーあり: テーマを 1 つに固定し、曲の頭から終わりへ「起 → 承 → 転 → 結」と場面が進む
  - ストーリーなし: 1 行ずつ場面（やテーマ）をばらばらに選ぶ。言葉遊びのような歌詞になる
  - 偶数行は前の行と最後の母音をそろえる（韻）ようにする

外部の AI を使わないので、インターネットや API キーなしで動く（exe 版でも使える）。
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .lyrics import split_mora

STAGES = ("起", "承", "転", "結")

# テーマ → 場面 → フレーズ片（ひらがな中心。モーラ数は自動で数える）
BANK: dict[str, dict[str, list[str]]] = {
    "恋": {
        "起": ["はじめてあった", "きみのよこがお", "めがあったひ", "さくらのしたで", "ちいさなこえで", "なまえをよんだ",
               "むねがなった", "はるのかぜ", "まちあわせ", "えきのホームで", "ふとふりむいた", "やさしいえがお"],
        "承": ["てをつないで", "ふたりでわらった", "よるのでんわ", "かえりみち", "おなじかさ", "ゆうやけぞら",
               "すきなうた", "きみのくせ", "ならんであるく", "まいにちが", "きらきらしてた", "メッセージ"],
        "転": ["すれちがって", "いえなかった", "なみだのあと", "とおくなる", "ことばがたりない", "ひとりのよる",
               "あめがふる", "こころがゆれた", "あいたくて", "ふあんになる", "せなかをみてた", "とどかない"],
        "結": ["すきだよって", "いまいうよ", "きみがすき", "ずっとそばに", "てをはなさない", "あしたもいっしょ",
               "このおもい", "とどけたい", "ふたりでいこう", "やくそくする", "わらっていて", "あいしてる"],
    },
    "友情": {
        "起": ["きょうしつで", "となりのせき", "はじめのあいさつ", "こえかけた", "おなじクラブ", "ほうかご",
               "グラウンドで", "まどべのせき", "あたらしいかお", "はるのあさ"],
        "承": ["ばかなはなし", "おなかかかえて", "わらいころげた", "じてんしゃで", "どこまでも", "なつやすみ",
               "うみへいった", "ゆめをかたった", "よるがあけるまで", "いつものばしょ", "ハイタッチ", "かたをくんだ"],
        "転": ["けんかして", "くちをきかない", "わかれのはる", "ちがうみち", "さみしくて", "とおいまち",
               "ひとりでないた", "ふりかえれば", "あのころには", "もどれないけど"],
        "結": ["ありがとう", "またあおう", "なかまだよ", "わすれない", "どこにいても", "つながってる",
               "だいじょうぶ", "いつだって", "きみがいる", "ずっとともだち", "わらっていこう", "かたをならべて"],
    },
    "夢": {
        "起": ["ちいさなころ", "ゆめをみた", "そらをみあげて", "かぜがふく", "はじまりのひ", "まどをあけて",
               "あさがきた", "まっしろなノート", "こころにちかった", "ほしにねがった"],
        "承": ["いっぽずつ", "あるいてきた", "あせをかいて", "なんどもころんで", "たちあがる", "まいにちを",
               "かさねてく", "れんしゅうして", "みちのとちゅう", "ちずをひろげて"],
        "転": ["うまくいかない", "くやしくて", "なみだがでた", "あきらめかけた", "かべがたかい", "まよいみち",
               "ひとりきり", "やみのなか", "こころがおれそう", "とどかないそら"],
        "結": ["まだいける", "あきらめない", "とびたとう", "あしたへゆこう", "ゆめのつづき", "かがやいて",
               "そらのむこう", "どこまでも", "まえをむいて", "はしりだせ", "いまをいきる", "ひかりのほうへ"],
    },
    "夏": {
        "起": ["せみがないた", "あおいそら", "なつがきた", "にゅうどうぐも", "まぶしいひ", "ビーチサンダル",
               "しおかぜ", "なつやすみ", "むぎわらぼうし", "ひまわりばたけ"],
        "承": ["うみへいこう", "なみうちぎわ", "かきごおり", "すいかわり", "はしゃいでた", "まつりのよる",
               "ゆかたすがた", "きんぎょすくい", "ラムネのびん", "ひやけしたかた"],
        "転": ["はなびがきえて", "なつのおわり", "ゆうだちが", "かえりみち", "さみしくなる", "かぜがかわる",
               "せみのこえ", "とおくなる", "あきのけはい"],
        "結": ["またらいねん", "わすれない", "このなつを", "むねにしまう", "きらめいた", "ひかりのなか",
               "わらいあった", "さいこうのなつ", "ありがとう", "またあおう"],
    },
    "冬": {
        "起": ["ゆきがふる", "しろいいき", "ふゆのあさ", "まっしろなまち", "マフラーまいて", "さむいよる",
               "イルミネーション", "こたつのなか", "ほしがきれい"],
        "承": ["てをあたためて", "ならんであるく", "ゆきだるま", "あったかいね", "ココアのんで", "まどのそと",
               "ふたりのあしあと", "ゆきあそび", "クリスマス"],
        "転": ["こごえるよる", "ひとりきり", "とどかないこえ", "つめたいかぜ", "ゆきがとける", "さよならのえき",
               "まちのあかり", "なみだがこおる"],
        "結": ["はるをまとう", "あたたかい", "ぬくもりを", "わすれない", "あなたのとなり", "ゆきのように",
               "しずかにふる", "おもいでを", "だきしめて"],
    },
    "ごはん": {
        "起": ["おなかがすいた", "いいにおい", "おひるやすみ", "なにたべよう", "メニューをひらく", "グーとなった",
               "きゅうしょくのじかん", "おみせのまえ", "ゆげがたつ"],
        "承": ["ラーメンすする", "カレーライス", "からあげ", "おにぎりほおばる", "あついスープ", "おかわり",
               "チーズがのびる", "やきそば", "ぎょうざとごはん", "たまごかけごはん"],
        "転": ["たべすぎた", "おなかがいっぱい", "うごけない", "ダイエットは", "あしたから", "さいふがからっぽ",
               "おさらがからっぽ", "ねむくなる"],
        "結": ["ごちそうさま", "しあわせだ", "おいしかった", "またたべよう", "いただきます", "まんぷくだ",
               "さいこうだ", "ありがとう", "またあした"],
    },
}

# どのテーマにも使える言葉
GENERIC: dict[str, list[str]] = {
    "起": ["いまここで", "はじまるよ", "ふとおもう", "あのひから", "きょうもまた"],
    "承": ["いつものように", "わらいながら", "ゆっくりと", "すこしずつ", "ふたりで"],
    "転": ["それでもね", "ほんとうは", "わからない", "なぜだろう", "ふりかえる"],
    "結": ["だいじょうぶ", "これからも", "いつまでも", "どこまでも", "きっとね"],
}

# 合いの手（余った数を埋める）。前に置くもの / 後ろに置くもの
FILL_HEAD = {1: ["あ"], 2: ["ねえ", "ほら", "いま", "ああ", "そう"], 3: ["ずっと", "きっと", "もっと", "ほらね"],
             4: ["らららら", "ねえきみ", "このまま"]}
FILL_TAIL = {1: ["よ", "ね", "さ"], 2: ["らら", "だよ", "かな"], 3: ["ららら", "いこう"], 4: ["らららら"]}

THEMES = list(BANK)

# 合いの手の長さの書き間違いを防ぐ（import 時に確認）
for _k, _words in list(FILL_HEAD.items()) + list(FILL_TAIL.items()):
    for _w in _words:
        assert len(split_mora(_w)) == _k, f"合いの手の長さが違います: {_w} は {_k} モーラではありません"


@dataclass(frozen=True)
class Frag:
    text: str
    mora: int
    vowel: str


def _frag(t: str) -> Frag:
    syl = split_mora(t)
    v = syl[-1].vowel if syl else "a"
    return Frag(t, len(syl), v)


_CACHE: dict[tuple[str, str], list[Frag]] = {}


def _pool(theme: str, stage: str) -> list[Frag]:
    key = (theme, stage)
    if key not in _CACHE:
        words = BANK[theme][stage] + GENERIC[stage]
        _CACHE[key] = [_frag(w) for w in dict.fromkeys(words)]
    return _CACHE[key]


def _fill(n: int, rng: random.Random) -> tuple[list[str], list[str]]:
    """n モーラ（1〜8）を合いの手で埋める。(前に置く, 後ろに置く)"""
    head, tail = [], []
    while n > 0:
        if n == 1 or (n <= 4 and rng.random() < 0.5):
            tail.append(rng.choice(FILL_TAIL[n]))
            n = 0
        else:
            k = min(n, 4)
            head.append(rng.choice(FILL_HEAD[k]))
            n -= k
    return head, tail


def make_line(n: int, pool: list[Frag], rng: random.Random, used: set[str], rhyme: str | None = None) -> str:
    """ちょうど n モーラの 1 行。"""
    if n <= 0:
        return ""
    if n <= 3:
        h, t = _fill(n, rng)
        return " ".join(h + t)
    best = None
    for _ in range(60):
        rem = n
        parts: list[Frag] = []
        while rem > 0 and len(parts) < (4 if n > 20 else 3):
            cands = [f for f in pool if f.mora <= rem and f.text not in used and f not in parts]
            # 余りが 1〜2 だけ残るより、ぴったりか 3 以上残る方がよい
            good = [f for f in cands if rem - f.mora == 0 or rem - f.mora >= 3]
            cands = good or cands
            if not cands:
                break
            f = rng.choice(cands)
            parts.append(f)
            rem -= f.mora
        head, tail = _fill(rem, rng) if rem > 0 else ([], [])
        fill_m = rem
        last_vowel = parts[-1].vowel if parts and not tail else (split_mora(tail[-1])[-1].vowel if tail else "a")
        score = fill_m * 2 + (0 if rhyme is None or last_vowel == rhyme else 1.5) + rng.random() * 0.5
        if best is None or score < best[0]:
            best = (score, head, parts, tail)
        if score < 0.6:
            break
    _, head, parts, tail = best
    for f in parts:
        used.add(f.text)
    return " ".join(head + [f.text for f in parts] + tail)


def generate(sections: list[tuple[str, list[int]]], story: bool = True, theme: str | None = None,
             seed: int | None = None) -> tuple[dict[str, str], str]:
    """sections: [(セクション名, [フレーズごとのモーラ数...]), ...]（曲の順）。

    返り値: ({セクション名: 歌詞（フレーズごとに改行）}, 使ったテーマ)
    """
    rng = random.Random(seed)
    if not theme or theme not in BANK:
        theme = rng.choice(THEMES)
    total = sum(len(c) for _, c in sections) or 1
    used: set[str] = set()
    out: dict[str, str] = {}
    gi = 0
    for name, counts in sections:
        lines = []
        prev_vowel = None
        for k, n in enumerate(counts):
            if story:
                stage = STAGES[min(3, gi * 4 // total)]
                th = theme
            else:
                stage = rng.choice(STAGES)
                th = theme if rng.random() < 0.6 else rng.choice(THEMES)
            pool = _pool(th, stage)
            if len(used) > len(pool) * 0.8:  # 使い切りそうなら再利用を許す
                used.difference_update(f.text for f in pool)
            rhyme = prev_vowel if k % 2 == 1 else None
            line = make_line(n, pool, rng, used, rhyme)
            lines.append(line)
            syl = split_mora(line)
            prev_vowel = syl[-1].vowel if syl else None
            gi += 1
        out[name] = "\n".join(lines)
    return out, theme


def phrase_counts(song) -> list[tuple[str, list[int]]]:
    """曲の各セクション（構成順・重複なし・メロディのあるもの）の、フレーズごとの数。

    元の歌詞があればそのフレーズごとのモーラ数、なければメロディのフレーズごとの歌う音の数
    （アプリの替え歌画面に出る数と同じ）。
    """
    from .kaeuta import melody_phrases
    from .lyrics import phrases as lyric_phrases
    from .song import _resolve_spec, parse_melody

    out = []
    for name in dict.fromkeys(song.structure):
        sec = song.sections[name]
        # 替え歌は「元のメロディ」（base: の自動調整前）に歌詞を合わせるので、それで数える
        spec = _resolve_spec(name, song.raw.get("sections") or {})
        notes, _ = parse_melody(spec.get("melody", ""), song.beats_per_bar)
        if not any(not n.is_rest for n in notes):
            continue
        sung = sum(1 for n in notes if not n.is_rest and not n.melisma)
        lyr = []
        if spec.get("lyrics"):
            try:
                lyr = [len(p) for p in lyric_phrases(split_mora(spec["lyrics"]))]
            except ValueError:
                lyr = []
        if lyr and sum(lyr) == sung:
            counts = lyr  # 元の歌詞が音符とぴったり → その区切りを使う
        else:
            # 音符の数に合わせる（元の歌詞の行数を目安に、長い音の後ろでも区切る）
            counts = [sum(1 for i in g if not notes[i].is_rest and not notes[i].melisma)
                      for g in melody_phrases(notes, len(lyr) or None)]
        out.append((name, [c for c in counts if c > 0]))
    return out
