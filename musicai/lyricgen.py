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


def generate(sections: list[tuple[str, list[int]]], story: bool = True, theme: str | None = None,
             seed: int | None = None, originals: dict[str, list[str]] | None = None) -> tuple[dict[str, str], str]:
    """sections: [(セクション名, [フレーズごとのモーラ数...]), ...]（曲の順）。

    originals: {セクション名: [元の歌詞の各行]}（あれば原曲の「くり返し」と「韻」をまねる）
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
                rhyme = _last_vowel(o) if o else (prev_vowel if k % 2 == 1 else None)
                line = make_line(n, pool, rng, used, rhyme)
                if key:
                    same_as_orig[key] = line
            lines.append(line)
            prev_vowel = _last_vowel(line)
            gi += 1
        out[name] = "\n".join(lines)
    return out, theme


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
                lyr_lines = ["".join(s.text for s in p if not s.melisma) for p in ph]
            except ValueError:
                lyr = []
        if lyr and sum(lyr) == sung:
            counts = lyr  # 元の歌詞が音符とぴったり → その区切りを使う
        else:
            # 音符の数に合わせる（元の歌詞の行数を目安に、長い音の後ろでも区切る）
            groups = merge_small_phrases(notes, melody_phrases(notes, len(lyr) or None))
            counts = [sum(1 for i in g if not notes[i].is_rest and not notes[i].melisma) for g in groups]
        if lyr_lines and len(lyr_lines) == len(counts):
            originals[name] = lyr_lines
        out.append((name, [c for c in counts if c > 0]))
    return (out, originals) if with_originals else out
