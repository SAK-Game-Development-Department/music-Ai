"""歌詞の自動生成（オフライン・ルールベース）。

替え歌で「フレーズごとの音の数」がわかっているとき、ちょうどその数のモーラになる歌詞を作る。

しくみ:
  - テーマ別・場面別（起・承・転・結）に、自然に読める言葉のかたまり（フレーズ片）を用意
  - フレーズ片は 2 種類に分けてある
      つなぎ … 「〜て」「〜で」「〜が」「〜けど」などで終わり、あとに言葉が続くもの
      しめ   … 文として終われるもの（「わらってた」「あおいそら」など）
    1 行は必ず「（つなぎ）＋ しめ」の形にするので、途中で切れた文が行末に来ない
  - 1 行の長さは目標モーラ数ちょうど。ぴったり作れないときだけ、自然な合いの手（行頭の「ねえ」、行末の「〜よ」など）で合わせる
  - ストーリーあり: テーマを 1 つに固定し、曲の頭から終わりへ「起 → 承 → 転 → 結」と場面が進む
  - ストーリーなし: 1 行ずつ場面（やテーマ）をばらばらに選ぶ。言葉遊びのような歌詞になる
  - 元の歌詞があるときは「原曲と同じ感じ」に寄せる:
      同じ行の長さ / 原曲で同じ歌詞がくり返す所（サビなど）は、新しい歌詞も同じ行をくり返す /
      各行の最後の母音（韻）を原曲にそろえる
  - 元の歌詞がないときは、偶数行の最後の母音を前の行にそろえる（韻）

外部の AI を使わないので、インターネットや API キーなしで動く（exe 版でも使える）。
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .lyrics import split_mora

STAGES = ("起", "承", "転", "結")

# テーマ → 場面 → フレーズ片（ひらがな中心。モーラ数・種類は自動で判定）
BANK: dict[str, dict[str, list[str]]] = {
    "恋": {
        "起": ["はじめてあった", "きみのよこがお", "めがあったひ", "さくらのしたで", "ちいさなこえで", "なまえをよんだ",
               "むねがなった", "はるのかぜ", "まちあわせ", "えきのホームで", "ふとふりむいた", "やさしいえがお",
               "あのひきみが", "わらってた", "きみをみつけた", "こいにおちた", "どきどきしてた", "はるのひに",
               "ことばをさがして", "まちかどで", "であったの"],
        "承": ["てをつないで", "ふたりでわらった", "よるのでんわ", "かえりみち", "おなじかさ", "ゆうやけぞら",
               "すきなうた", "きみのくせ", "ならんであるく", "まいにちが", "きらきらしてた", "メッセージ",
               "ふたりで", "おなじうたを", "くちずさんだ", "あしたのことを", "はなしてた", "きみのとなりで",
               "ねむれないよる", "こえをきいてた", "しあわせだった"],
        "転": ["すれちがって", "いえなかった", "なみだのあと", "とおくなる", "ことばがたりない", "ひとりのよる",
               "あめがふる", "こころがゆれた", "あいたくて", "ふあんになる", "せなかをみてた", "とどかない",
               "ほんとうは", "つたえたいのに", "めをそらした", "きみがいない", "へやのなかで", "わからないまま",
               "ないていた"],
        "結": ["すきだよって", "いまいうよ", "きみがすき", "ずっとそばに", "てをはなさない", "あしたもいっしょ",
               "このおもい", "とどけたい", "ふたりでいこう", "やくそくする", "わらっていて", "あいしてる",
               "なんどでも", "きみをまもる", "いつまでも", "そばにいるよ", "このてで", "だきしめたい"],
    },
    "友情": {
        "起": ["きょうしつで", "となりのせき", "はじめのあいさつ", "こえかけた", "おなじクラブ", "ほうかごの",
               "グラウンドで", "まどべのせき", "あたらしいかお", "はるのあさ", "きみとであった", "はなしかけた",
               "なまえをおぼえた", "わらいあった", "いつのまにか", "ともだちになった"],
        "承": ["ばかなはなしで", "おなかかかえて", "わらいころげた", "じてんしゃで", "どこまでもいった", "なつやすみ",
               "うみへいった", "ゆめをかたった", "よるがあけるまで", "いつものばしょで", "ハイタッチした", "かたをくんだ",
               "おなじゆめを", "みていたね", "むちゅうになって", "はしりまわった"],
        "転": ["けんかして", "くちをきかない", "わかれのはる", "ちがうみちへ", "さみしくて", "とおいまちで",
               "ひとりでないた", "ふりかえれば", "あのころには", "もどれないけど", "さよならが", "いえなかった",
               "それぞれのみち", "あるきだした"],
        "結": ["ありがとう", "またあおう", "なかまだよ", "わすれない", "どこにいても", "つながってる",
               "だいじょうぶ", "いつだって", "きみがいる", "ずっとともだち", "わらっていこう", "かたをならべて",
               "あのそらに", "ちかったゆめを", "かなえよう"],
    },
    "夢": {
        "起": ["ちいさなころ", "ゆめをみた", "そらをみあげて", "かぜがふく", "はじまりのひ", "まどをあけて",
               "あさがきた", "まっしろなノート", "こころにちかった", "ほしにねがった", "いつかきっと", "あのばしょへ",
               "ゆめのとびらを", "ひらいたんだ"],
        "承": ["いっぽずつ", "あるいてきた", "あせをかいて", "なんどもころんで", "たちあがった", "まいにちを",
               "かさねてきた", "れんしゅうして", "みちのとちゅうで", "ちずをひろげて", "まえだけみて", "はしってきた",
               "ちいさなひかりを", "しんじてた"],
        "転": ["うまくいかない", "くやしくて", "なみだがでた", "あきらめかけた", "かべがたかい", "まよいみち",
               "ひとりきり", "やみのなかで", "こころがおれそう", "とどかないそら", "それでも", "わすれられない",
               "あのひのゆめが"],
        "結": ["まだいける", "あきらめない", "とびたとう", "あしたへゆこう", "ゆめのつづきへ", "かがやいて",
               "そらのむこうへ", "どこまでも", "まえをむいて", "はしりだせ", "いまをいきる", "ひかりのほうへ",
               "このてで", "つかみとる", "あたらしいみちを", "ひらいていこう"],
    },
    "夏": {
        "起": ["せみがないた", "あおいそら", "なつがきた", "にゅうどうぐも", "まぶしいひ", "ビーチサンダル",
               "しおかぜに", "ふかれて", "むぎわらぼうし", "ひまわりばたけ", "あついひざしが", "はじまった",
               "なつのあさ"],
        "承": ["うみへいこう", "なみうちぎわで", "かきごおり", "すいかわり", "はしゃいでた", "まつりのよる",
               "ゆかたすがた", "きんぎょすくい", "ラムネのびん", "ひやけしたかた", "はなびをみた", "よぞらにさいた",
               "ふたりで", "わらいあった"],
        "転": ["はなびがきえて", "なつのおわり", "ゆうだちが", "かえりみち", "さみしくなる", "かぜがかわる",
               "せみのこえが", "とおくなる", "あきのけはい", "すこしだけ", "せつなくて"],
        "結": ["またらいねん", "わすれない", "このなつを", "むねにしまう", "きらめいた", "ひかりのなか",
               "わらいあった", "さいこうのなつ", "ありがとう", "またあおう", "なつのそらよ", "いつまでも"],
    },
    "冬": {
        "起": ["ゆきがふる", "しろいいき", "ふゆのあさ", "まっしろなまち", "マフラーまいて", "さむいよる",
               "イルミネーション", "こたつのなかで", "ほしがきれい", "まちのあかりが", "ともりはじめた"],
        "承": ["てをあたためて", "ならんであるく", "ゆきだるま", "あったかいね", "ココアをのんで", "まどのそと",
               "ふたりのあしあと", "ゆきあそび", "クリスマス", "プレゼントを", "えらんでた"],
        "転": ["こごえるよる", "ひとりきり", "とどかないこえ", "つめたいかぜが", "ゆきがとける", "さよならのえき",
               "まちのあかり", "なみだがこおる", "なにもいえず", "たちつくした"],
        "結": ["はるをまとう", "あたたかい", "ぬくもりを", "わすれない", "あなたのとなり", "ゆきのように",
               "しずかにふる", "おもいでを", "だきしめて", "ずっとそばに", "いさせてね"],
    },
    "ごはん": {
        "起": ["おなかがすいた", "いいにおい", "おひるやすみ", "なにたべよう", "メニューをひらいて", "グーとなった",
               "きゅうしょくのじかん", "おみせのまえで", "ゆげがたつ", "まちきれない"],
        "承": ["ラーメンすする", "カレーライス", "からあげ", "おにぎりほおばる", "あついスープを", "おかわりした",
               "チーズがのびる", "やきそば", "ぎょうざとごはん", "たまごかけごはん", "ほっぺがおちる", "おいしくて"],
        "転": ["たべすぎた", "おなかがいっぱい", "うごけない", "ダイエットは", "あしたからにする", "さいふがからっぽ",
               "おさらがからっぽ", "ねむくなる", "それでも", "デザートは", "べつばらだ"],
        "結": ["ごちそうさま", "しあわせだ", "おいしかった", "またたべよう", "いただきます", "まんぷくだ",
               "さいこうだ", "ありがとう", "またあした", "みんなでたべる", "ごはんがすき"],
    },
}

# どのテーマにも使える言葉
GENERIC: dict[str, list[str]] = {
    "起": ["いまここで", "はじまるよ", "ふとおもう", "あのひから", "きょうもまた"],
    "承": ["いつものように", "わらいながら", "ゆっくりと", "すこしずつ", "ふたりで"],
    "転": ["それでもね", "ほんとうは", "わからない", "なぜだろう", "ふりかえる"],
    "結": ["だいじょうぶ", "これからも", "いつまでも", "どこまでも", "きっとね"],
}

# 合いの手（ぴったり作れないときだけ使う）。行頭に置くもの / 行末に付けるもの
FILL_HEAD = {2: ["ねえ", "ほら", "ああ", "いま"], 3: ["ずっと", "きっと", "そっと"], 4: ["ねえきみ", "このまま"]}
FILL_TAIL = {1: ["よ", "ね"], 2: ["だよ", "かな"]}
# 1〜3 モーラだけの行（とても短いフレーズ）
SHORT = {1: ["ら"], 2: ["ねえ", "ほら", "ああ", "らら"], 3: ["ららら", "ずっと", "きっと"],
         4: ["いまでも", "このまま", "あいたい", "だいすき"], 5: ["いつまでも", "どこまでも", "ありがとう", "だいじょうぶ"]}

# 「つなぎ」（あとに言葉が続く）とみなす語尾
LEAD_ENDINGS = ("て", "で", "が", "を", "は", "に", "と", "の", "ば", "けど", "から", "のに", "たら", "ても")
# どこにでも置ける副詞（つなぎとして使う）
ADVERBS = {"いつまでも", "どこまでも", "いつだって", "なんどでも", "すこしずつ", "ゆっくりと", "いっぽずつ",
           "いつのまにか", "ふたりで", "それでも", "いつかきっと", "すこしだけ", "このてで"}

THEMES = list(BANK)

for _k, _words in list(FILL_HEAD.items()) + list(FILL_TAIL.items()) + list(SHORT.items()):
    for _w in _words:
        assert len(split_mora(_w)) == _k, f"合いの手の長さが違います: {_w} は {_k} モーラではありません"


@dataclass(frozen=True)
class Frag:
    text: str
    mora: int
    vowel: str
    lead: bool  # True = つなぎ（行末に置かない）


def _frag(t: str) -> Frag:
    syl = split_mora(t)
    v = syl[-1].vowel if syl else "a"
    lead = t in ADVERBS or t.endswith(LEAD_ENDINGS)
    return Frag(t, len(syl), v, lead)


_CACHE: dict[tuple[str, str], tuple[list[Frag], list[Frag]]] = {}


def _pool(theme: str, stage: str) -> tuple[list[Frag], list[Frag]]:
    """(つなぎ, しめ) のフレーズ片。"""
    key = (theme, stage)
    if key not in _CACHE:
        frags = [_frag(w) for w in dict.fromkeys(BANK[theme][stage] + GENERIC[stage])]
        _CACHE[key] = ([f for f in frags if f.lead], [f for f in frags if not f.lead])
    return _CACHE[key]


def _last_vowel(text: str) -> str | None:
    for s in reversed(split_mora(text)):
        if s.vowel in "aiueo":
            return s.vowel
    return None


def make_line(n: int, pool: tuple[list[Frag], list[Frag]], rng: random.Random, used: set[str],
              rhyme: str | None = None) -> str:
    """ちょうど n モーラの 1 行。形は「（合いの手）（つなぎ）（つなぎ）しめ（〜よ）」。"""
    if n <= 0:
        return ""
    if n <= 3:
        return rng.choice(SHORT[n])
    leads, ends = pool
    best = None

    def consider(parts: list[Frag], head: str = "", tail: str = ""):
        nonlocal best
        filler = (len(split_mora(head)) if head else 0) + (len(split_mora(tail)) if tail else 0)
        end_vowel = _last_vowel(tail) if tail else parts[-1].vowel
        score = (filler * 3 + sum(2 for f in parts if f.text in used) + (len(parts) - 1) * 0.3
                 + (0 if rhyme is None or end_vowel == rhyme else 1.2) + rng.random() * 0.8)
        if best is None or score < best[0]:
            best = (score, head, parts, tail)

    by_len: dict[int, list[Frag]] = {}
    for f in leads:
        by_len.setdefault(f.mora, []).append(f)
    end_list = ends[:]
    rng.shuffle(end_list)
    for e in end_list:
        rest = n - e.mora
        if rest == 0:
            consider([e])
        elif rest > 0:
            same = by_len.get(rest, [])
            for f in rng.sample(same, min(3, len(same))):  # つなぎ 1 つ
                consider([f, e])
            if rest >= 6:  # つなぎ 2 つ（長い行）
                for f1 in rng.sample(leads, min(12, len(leads))):
                    for f2 in by_len.get(rest - f1.mora, [])[:2]:
                        if f2 is not f1:
                            consider([f1, f2, e])
            # 合いの手で合わせる（最後の手段）
            for k, words in FILL_HEAD.items():
                if rest == k:
                    consider([e], head=rng.choice(words))
                elif rest - k > 0:
                    for f in by_len.get(rest - k, [])[:1]:
                        consider([f, e], head=rng.choice(words))
            for k, words in FILL_TAIL.items():
                if rest == k:
                    consider([e], tail=rng.choice(words))
                elif rest - k > 0:
                    for f in by_len.get(rest - k, [])[:1]:
                        consider([f, e], tail=rng.choice(words))
        if best is not None and best[0] < 0.5:
            break
    if best is None and n in SHORT:  # 短い行で、ぴったりの言葉がないとき
        return rng.choice(SHORT[n])
    if best is None:  # とても長い行など: 2 行ぶんを作ってつなぐ
        a = n // 2
        return make_line(a, pool, rng, used, None) + " " + make_line(n - a, pool, rng, used, rhyme)
    _, head, parts, tail = best
    for f in parts:
        used.add(f.text)
    return " ".join(([head] if head else []) + [f.text for f in parts]) + (tail or "")


# 原曲の行末から引きつぐ語尾（終助詞など）
KEEP_ENDINGS = ("よ", "ね", "さ", "わ", "ぞ")


def _kana_words(line: str) -> list[str]:
    """原曲の行 → 言葉（よみ）の並び。漢字の読みは reading で調べる。"""
    from .reading import ReadingUnavailable, words

    try:
        return [w for w in words(line) if w.strip() and w.strip() not in ("、", "。")]
    except ReadingUnavailable:
        return [line]


def _mora(text: str) -> int:
    return len([s for s in split_mora(text) if not s.melisma])


def find_hooks(lines: list[str]) -> set[str]:
    """原曲で 2 回以上出てくる 3 モーラ以上の言葉（サビの「決めの言葉」など）。"""
    count: dict[str, int] = {}
    for ln in dict.fromkeys(lines):  # 同じ行のくり返し（サビの 2 回目など）は 1 回と数える
        for w in set(_kana_words(ln)):
            w = w.strip()
            try:
                if _mora(w) >= 3:
                    count[w] = count.get(w, 0) + 1
            except ValueError:
                pass
    return {w for w, c in count.items() if c >= 2}


def _plan_from_original(orig: str, n: int, hooks: set[str]) -> tuple[str, str, str]:
    """原曲の行から (先頭に残す決めの言葉, 末尾に残す語尾, —) を決める。残りの長さは呼び出し側で計算。"""
    ws = [w.strip() for w in _kana_words(orig) if w.strip()]
    head = ""
    tail = ""
    if ws and ws[0] in hooks:
        head = ws[0]
        # 「ありがとう ありがとう」のように続けてくり返すときはまとめて残す
        if len(ws) > 1 and ws[1] == ws[0]:
            head = ws[0] + " " + ws[1]
    try:
        kana = "".join(s.text for s in split_mora(orig_kana(orig)))
    except ValueError:
        kana = ""
    if kana.endswith(KEEP_ENDINGS) and not (head and kana.endswith(head.replace(" ", ""))):
        tail = kana[-1]
    if _mora(head.replace(" ", "")) + len(tail) >= n - 2:  # 残りが短すぎるなら残さない
        head = ""
    return head, tail, ""


def orig_kana(line: str) -> str:
    from .reading import ReadingUnavailable, to_ruby

    try:
        return to_ruby(line)
    except ReadingUnavailable:
        return line


# ---------------------------------------------------------------- 原曲の骨組みを残して言葉を入れ替える
# テーマごとの名詞（原曲の名詞と同じ長さのものと入れ替える）
NOUNS: dict[str, list[str]] = {
    "恋": ["きみ", "ぼく", "て", "め", "こえ", "ゆめ", "そら", "はな", "こい", "むね", "ほほ", "えがお", "ひとみ",
          "こころ", "ことば", "おもい", "なみだ", "やくそく", "ゆびさき", "てがみ", "ふたり", "あした", "さくら", "はる"],
    "友情": ["きみ", "とも", "かた", "て", "ゆめ", "そら", "みち", "なかま", "ともだち", "えがお", "きずな", "ほうかご",
            "きょうしつ", "グラウンド", "なつ", "はる", "あした", "おもいで", "じてんしゃ", "ふたり"],
    "夢": ["ゆめ", "そら", "ほし", "みち", "かぜ", "て", "ひかり", "みらい", "あした", "つばさ", "とびら", "ちず",
          "ゴール", "スタート", "こころ", "なみだ", "あせ", "いっぽ", "はじまり", "きぼう"],
    "夏": ["なつ", "うみ", "そら", "なみ", "かぜ", "せみ", "くも", "ひ", "すいか", "はなび", "まつり", "ゆかた",
          "ひまわり", "ラムネ", "かきごおり", "ビーチ", "しおかぜ", "ゆうだち", "なつやすみ", "むぎわら"],
    "冬": ["ゆき", "ふゆ", "かぜ", "よる", "ほし", "て", "いき", "こたつ", "マフラー", "てぶくろ", "ゆきだるま",
          "イルミネーション", "ぬくもり", "ココア", "みかん", "クリスマス", "まち", "ひかり", "ふたり"],
    "ごはん": ["めし", "パン", "めん", "こめ", "さら", "ラーメン", "カレー", "からあげ", "おにぎり", "ぎょうざ", "スープ",
            "おかず", "たまご", "デザート", "やきそば", "おやつ", "べんとう", "おなか", "さいふ", "はし"],
}
# 形容詞（名詞の前に付くもの）
ADJECTIVES = ["あおい", "あかい", "しろい", "あつい", "ながい", "まるい", "やさしい", "まぶしい", "うれしい", "さみしい",
              "ちいさな", "おおきな", "あたらしい", "なつかしい", "つめたい", "あたたかい", "おいしい", "きらきらの",
              "まっしろな", "まっさおな", "ひみつの", "ふしぎな"]
# 残す言葉（助詞・語尾など）
FUNCTION_WORDS = {"は", "が", "を", "に", "の", "で", "と", "も", "へ", "や", "よ", "ね", "さ", "わ", "な", "か", "ぞ",
                  "から", "まで", "けど", "より", "だけ", "て", "た", "だ", "う", "ない", "たら", "ば", "ら",
                  "でも", "なら", "って", "ても",
                  # 原曲のまま残す副詞など（言い回しの骨組み。行の頭でもよい）
                  "まだ", "もう", "また", "ずっと", "きっと", "いつも", "いつか", "どこ", "なぜ", "そっと", "もっと",
                  "ほら", "ねえ", "ああ", "ただ", "すこし", "とても", "いま"}
_VERB_END = tuple("たるうくすつぬむぶぐいだ")
ADVERBS_KEEP = {"まだ", "もう", "また", "ずっと", "きっと", "いつも", "いつか", "どこ", "なぜ", "そっと", "もっと",
                "ほら", "ねえ", "ああ", "ただ", "すこし", "とても", "いま"}


def _verb_pool(theme: str, stage: str | None) -> tuple[list[Frag], list[Frag]]:
    """(て形などの「つなぎ」の動詞句, 文末の動詞・形容詞句)。場面を指定すればその場面から。"""
    stages = [stage] if stage else list(STAGES)
    te, end = [], []
    for st in stages:
        leads, ends = _pool(theme, st)
        te += [f for f in leads if f.text.endswith(("て", "で"))]
        end += [f for f in ends if f.text.endswith(_VERB_END)]
    return te, end


_PARTICLES = ("から", "まで", "けど", "は", "が", "を", "に", "も", "で", "と", "の", "へ")


def _chunks(line: str) -> list[tuple[str, str, str]]:
    """原曲の 1 行 → [(種類, 表記, よみ)]。種類: fn（残す）/ noun / adj / pred（動詞・形容詞のまとまり）/ space"""
    from .reading import segments

    def kana(t):
        return all("ぁ" <= c <= "ゖ" or c == "ー" for c in t)

    segs = [(o, y) for o, y in segments(line)]
    out: list[tuple[str, str, str]] = []
    i = 0
    while i < len(segs):
        o, y = segs[i]
        first = not any(k != "space" for k, _, _ in out)
        nxt = segs[i + 1][0] if i + 1 < len(segs) else ""
        if not o.strip():
            out.append(("space", o, y))
            i += 1
            continue
        has_kanji = any("\u3400" <= c <= "\u9fff" for c in o)
        if kana(o) and o in FUNCTION_WORDS and (not first or o in ADVERBS_KEEP):
            out.append(("fn", o, y))
            i += 1
            continue
        if kana(o):
            # かなだけのまとまり。先頭の助詞は残す（行の最初は助詞ではない）
            head = "" if first else next((p for p in _PARTICLES if o.startswith(p) and len(o) > len(p) + 1), "")
            if head:
                out.append(("fn", head, head))
                o, y = o[len(head):], y[len(head):]
            # 後ろの助詞（の・を など）は名詞 + 助詞、文末の よ・ね は残す
            tailp = next((p for p in ("の", "を", "が", "に", "は", "も", "へ") if o.endswith(p) and len(o) > 2), "")
            if tailp:
                out.append(("noun", o[: -len(tailp)], y[: -len(tailp)]))
                out.append(("fn", tailp, tailp))
            else:
                tail = o[-1] if o[-1] in ("よ", "ね") and len(o) > 2 else ""
                out.append(("pred", o[: len(o) - len(tail)], y[: len(y) - len(tail)]))
                if tail:
                    out.append(("fn", tail, tail))
            i += 1
            continue
        # 「僕ら」「君たち」は名詞
        noun_suffix = has_kanji and (o.endswith("ら") or o.endswith("たち")) and not o.endswith(("たら", "ら゛"))
        stem = has_kanji and "ぁ" <= o[-1] <= "ゖ" and not noun_suffix  # 「運ん」「走り」のような動詞の語幹
        if has_kanji and nxt == "な" and stem:
            out.append(("adj", o + nxt, y + segs[i + 1][1]))  # 「小さ」+「な」→ 形容詞
            i += 2
            continue
        if has_kanji and nxt and kana(nxt) and (stem or not nxt.startswith(_PARTICLES + ("よ", "ね", "さ", "わ", "ぞ"))):
            # 動詞の語幹 + 活用（「開け」+「たら」、「歩い」+「てゆくよ」）→ ひとまとまり。文末の よ/ね は残す
            tail_o, tail_y = segs[i + 1]
            keep = tail_o[-1] if tail_o.endswith(("よ", "ね")) and len(tail_o) > 1 else ""
            out.append(("pred", o + tail_o[: len(tail_o) - len(keep)], y + tail_y[: len(tail_y) - len(keep)]))
            if keep:
                out.append(("fn", keep, keep))
            i += 2
            continue
        if has_kanji and o.endswith("い") and not o.endswith("ない"):
            out.append(("adj", o, y))  # 「新しい」など（名詞の前）
            i += 1
            continue
        # 漢字 + 後ろの助詞（「歌を」）→ 名詞 + 助詞
        tailp = next((p for p in ("を", "が", "に", "は", "の", "で", "と", "も", "へ") if has_kanji and o.endswith(p)
                      and len(o) > 1), "")
        if tailp:
            out.append(("noun", o[: -len(tailp)], y[: -len(tailp)]))
            out.append(("fn", tailp, tailp))
            i += 1
            continue
        if has_kanji and "ぁ" <= o[-1] <= "ゖ" and not noun_suffix:
            out.append(("pred", o, y))  # 「光る」「届け」のように送りがな付き
            i += 1
            continue
        out.append(("noun", o, y))
        i += 1
    # 続いた動詞のまとまり（「走り」+「出す」）は 1 つにする
    merged: list[tuple[str, str, str]] = []
    for c in out:
        if merged and c[0] == "pred" and merged[-1][0] == "pred":
            merged[-1] = ("pred", merged[-1][1] + c[1], merged[-1][2] + c[2])
        else:
            merged.append(c)
    return merged


def transform_line(line: str, theme: str, stage: str | None, rng: random.Random, used: set[str],
                   hooks: set[str]) -> str | None:
    """原曲の行の骨組み（助詞・語尾・決めの言葉）を残して、名詞・動詞・形容詞を同じ長さの言葉に入れ替える。

    同じ長さの言葉がないところは原曲の言葉のまま残す。入れ替えが半分未満なら None（ほかの作り方にまかせる）。
    """
    try:
        chunks = _chunks(line)
    except Exception:  # noqa: BLE001  読みが調べられないときなど
        return None
    nouns: dict[int, list[str]] = {}
    for w in NOUNS.get(theme, []):
        nouns.setdefault(_mora(w), []).append(w)
    adjs: dict[int, list[str]] = {}
    for w in ADJECTIVES:
        adjs.setdefault(_mora(w), []).append(w)
    te, end = _verb_pool(theme, stage)
    te_all, end_all = _verb_pool(theme, None)
    out: list[str] = []
    content = changed = 0
    line_words = {y for _, _, y in chunks}

    def ok(w: str) -> bool:  # 同じ行の言葉と重ならない（「ぼくらの ぼく」にしない）
        return w not in used and all(w not in x and x not in w for x in line_words if len(x) >= 2)

    for kind, o, y in chunks:
        if kind in ("fn", "space"):
            out.append(o if kind == "space" else y)
            continue
        if y.replace(" ", "") in hooks:  # くり返し出てくる決めの言葉は残す
            out.append(y)
            continue
        content += 1
        m = _mora(y)
        pick = None
        if kind == "noun":
            cands = [w for w in nouns.get(m, []) if ok(w)]
        elif kind == "adj":
            cands = [w for w in adjs.get(m, []) if ok(w)]
        else:
            is_te = y.endswith(("て", "で"))
            pools = (te, te_all) if is_te else (end, end_all)
            cands = []
            for pool in pools:
                cands = [f.text for f in pool if f.mora == m and ok(f.text)]
                if cands:
                    break
        if cands:
            pick = rng.choice(cands)
            used.add(pick)
            changed += 1
        out.append(pick or y)
    if content == 0 or changed * 2 < content:
        return None
    # 読みやすいように、助詞のあと（次に言葉が続くとき）で区切る
    text = ""
    for k, ((kind, _, _), w) in enumerate(zip(chunks, out)):
        if kind == "space":
            text += " "
            continue
        text += w
        nxt = chunks[k + 1][0] if k + 1 < len(chunks) else None
        if kind == "fn" and nxt in ("noun", "adj", "pred") and not text.endswith(" "):
            text += " "
    return text


def generate(sections: list[tuple[str, list[int]]], story: bool = True, theme: str | None = None,
             seed: int | None = None, originals: dict[str, list[str]] | None = None) -> tuple[dict[str, str], str]:
    """sections: [(セクション名, [フレーズごとのモーラ数...]), ...]（曲の順）。

    originals: {セクション名: [元の歌詞の各行（漢字まじりでよい）]}。あれば「原曲をきれいに替える」:
        行の長さ・くり返し・行末の韻に加えて、原曲の語尾（〜よ / 〜ね など）と、
        くり返し出てくる決めの言葉（行頭）を残し、残りの部分だけを新しい言葉にする
    返り値: ({セクション名: 歌詞（フレーズごとに改行）}, 使ったテーマ)
    """
    rng = random.Random(seed)
    if not theme or theme not in BANK:
        theme = rng.choice(THEMES)
    originals = originals or {}
    total = sum(len(c) for _, c in sections) or 1
    used: set[str] = set()
    out: dict[str, str] = {}
    same_as_orig: dict[tuple[str, int], str] = {}  # 原曲の同じ行 → 同じ新しい行（サビのくり返し）
    hooks = find_hooks([ln for lines in originals.values() for ln in lines])
    gi = 0
    for name, counts in sections:
        lines = []
        prev_vowel = None
        orig = originals.get(name) or []
        for k, n in enumerate(counts):
            o = orig[k] if k < len(orig) else None
            key = (o, n) if o else None
            if key and key in same_as_orig:
                line = same_as_orig[key]
            else:
                if story:
                    stage = STAGES[min(3, gi * 4 // total)]
                    th = theme
                else:
                    stage = rng.choice(STAGES)
                    th = theme if rng.random() < 0.6 else rng.choice(THEMES)
                pool = _pool(th, stage)
                names_in_pool = {f.text for f in pool[0] + pool[1]}
                if len(used & names_in_pool) > len(names_in_pool) * 0.7:  # この場面の言葉を使い切りそうなら再利用を許す
                    used.difference_update(names_in_pool)
                transformed = transform_line(o, th, stage if story else None, rng, used, hooks) if o else None
                if transformed is not None and _mora(transformed) == n:
                    line = transformed
                elif o:
                    keep_head, keep_tail, _ = _plan_from_original(o, n, hooks)
                    body_n = n - _mora(keep_head.replace(" ", "")) - len(keep_tail)
                    rhyme = None if keep_tail else _last_vowel(orig_kana(o))
                    body = make_line(body_n, pool, rng, used, rhyme) if body_n > 0 else ""
                    for _ in range(8):  # 「〜よよ」「〜ねね」にならないように作り直す
                        if not (keep_tail and body.endswith(keep_tail)):
                            break
                        body = make_line(body_n, pool, rng, used, None)
                    if keep_tail and body.endswith(keep_tail):
                        keep_tail = ""
                        body = make_line(n, pool, rng, used, None)
                    line = " ".join(x for x in (keep_head, body) if x) + keep_tail
                else:
                    rhyme = prev_vowel if k % 2 == 1 else None
                    line = make_line(n, pool, rng, used, rhyme)
                if key:
                    same_as_orig[key] = line
            lines.append(line)
            prev_vowel = _last_vowel(line)
            gi += 1
        out[name] = "\n".join(lines)
    return out, theme


def _display_lines(text: str) -> list[str]:
    """歌詞（{漢字|よみ} の書式）→ 表示用の行（漢字のまま）。"""
    from .lyrics import display_lyrics

    return display_lyrics(text)


def phrase_counts(song, with_originals: bool = False):
    """曲の各セクション（構成順・重複なし・歌うもの）の、フレーズごとの数。

    元の歌詞があればそのフレーズごとのモーラ数、なければメロディのフレーズごとの歌う音の数
    （アプリの替え歌画面に出る数と同じ）。間奏など歌わないパート（sing: false）は含めない。
    with_originals=True なら (一覧, {セクション名: 元の歌詞の各行}) を返す。
    """
    from .kaeuta import melody_phrases, merge_small_phrases
    from .lyrics import phrases as lyric_phrases
    from .song import _resolve_spec, parse_melody

    out = []
    originals: dict[str, list[str]] = {}
    for name in dict.fromkeys(song.structure):
        sec = song.sections[name]
        if not sec.sing:  # 間奏など、歌わないパートには歌詞を作らない
            continue
        # 替え歌は「元のメロディ」（base: の自動調整前）に歌詞を合わせるので、それで数える
        spec = _resolve_spec(name, song.raw.get("sections") or {})
        notes, _ = parse_melody(spec.get("melody", ""), song.beats_per_bar)
        if not any(not n.is_rest for n in notes):
            continue
        sung = sum(1 for n in notes if not n.is_rest and not n.melisma)
        lyr: list[int] = []
        lyr_lines: list[str] = []
        if spec.get("lyrics"):
            try:
                ph = lyric_phrases(split_mora(spec["lyrics"]))
                lyr = [len(p) for p in ph]
                lyr_lines = _display_lines(spec["lyrics"])
                if len(lyr_lines) != len(ph):
                    lyr_lines = ["".join(s.text for s in p if not s.melisma) for p in ph]
            except ValueError:
                lyr = []
        if lyr:
            counts = lyr  # 元の歌詞があれば、その行の長さのまま（原曲どおり。メロディは替え歌のとき自動で合わせる）
        else:
            # 音符の数に合わせる（元の歌詞の行数を目安に、長い音の後ろでも区切る）
            groups = merge_small_phrases(notes, melody_phrases(notes, len(lyr) or None))
            counts = [sum(1 for i in g if not notes[i].is_rest and not notes[i].melisma) for g in groups]
        if lyr_lines and len(lyr_lines) == len(counts):
            originals[name] = lyr_lines
        out.append((name, [c for c in counts if c > 0]))
    return (out, originals) if with_originals else out
