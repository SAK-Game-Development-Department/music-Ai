# 作曲プロンプト：テーマ・キー・テンポから作曲仕様（specs/xxx.yaml）を作る

あなたは作曲アシスタントです。下の「入力」から、musicai の**作曲仕様ファイル**を 1 つ作ってください。
メロディは書きません。`python -m musicai compose` が仕様から自動で作ります。

## 入力（ここを埋めて渡す）

- テーマ・物語: {{テーマ}}
- 雰囲気（明るい / 切ない など）: {{雰囲気}}
- キー: {{キー  例: G major / A minor}}
- テンポ: {{テンポ  例: 124}}
- 構成の希望（任意）: {{構成  例: intro, verse, prechorus, chorus, verse2, chorus, outro}}

## 守るべき形式（契約）

- スキーマ: `schemas/spec.schema.json`（先に読むこと）
- `schema_version: 1` を**必ず先頭に**書く
- 使えるキー以外は書かない（未知のキーは `validate` で不合格になる）
  - 全体: `schema_version title key tempo time style seed structure sections`
  - 各セクション: `progression chords chords_per_bar lyrics bars phrase_bars energy register transpose_range base fit`
- `style` は `pop / ballad / rock / simple`、`energy` と `register` は `low / mid / high`
- `structure` に並べた名前は、すべて `sections` に定義する。2 回目以降に同じ名前を並べると、同じパートの繰り返しになる

## 歌詞の書き方

- **1 行 = 1 フレーズ**（息継ぎまで）。1 行 5〜12 モーラ。対になる行はモーラ数を揃える
- ひらがな・カタカナで書く。**漢字は必ず `{漢字|よみ}`**（例: `{空|そら}`、`{今|いま}うたおう`）。読み指定が無い漢字は読み込みエラーになる
- 英語は単語ごと。音節は `-` で区切る（`twin-kle`）
- `~` は前の音を伸ばす印、`/` か改行はフレーズの区切り
- 「きょ」のような小さい文字は前の文字と合わせて 1 モーラ。「ー」「ん」「っ」は 1 モーラずつ
- 歌詞は YAML の複数行文字列（`lyrics: |`）で、1 行ずつ書く

## melody 記法（`songs/*.yaml` を読むとき・直すときの規則）

`melody: "音名:拍数 ..."` — 音名は `C4`（真ん中のド）・`F#4`・`Bb3`、拍数は `1` `0.5` `1/2`。
拍数を省略すると直前と同じ長さ、休符は `r`（`r:1`）、`~` を付けた音は新しい文字を歌わないメリスマ（`G4:1~`）、`|` は小節線。

## 作曲のルール（docs/01_音楽の作り方.md に沿う）

- Aメロは低め・静か、サビは一番高く（`energy: high`）。2 番は `base: <1 番のパート名>` で歌詞だけ替える
- コード進行は定番から選ぶ: 王道進行 / カノン進行 / 小室進行 / 丸サ進行 / ポップ・パンク進行（進行名・ディグリー・コード名のどれでも可）
- 各パートは 4 小節か 8 小節。インストのパート（intro / interlude / outro）は歌詞を書かず `bars` で小節数を指定する
- `seed` を変えると別のメロディ案になる

## 書き出す前に必ず実行する

1. 仕様を `specs/xxx.yaml` に保存する
2. `python -m musicai validate specs/xxx.yaml` → **合格**になるまで直す（ファイル構造の検証）
3. `python -m musicai compose specs/xxx.yaml` → `songs/xxx.yaml` ができる
4. `python -m musicai validate songs/xxx.yaml` と `python -m musicai check songs/xxx.yaml` を実行し、**警告ゼロ・音符数＝モーラ数**を確認する
5. 通ってから `python -m musicai render songs/xxx.yaml` で書き出す

## 出力形式

次の 2 つに**分けて**出力する。

1. **YAML のみ**（コードブロック 1 つ、`schema_version: 1` から始める。コメントは `#` で YAML の中に書いてよいが、説明文は入れない）
2. **説明**（YAML の外）: コンセプト、キーとコード進行を選んだ理由（理論の根拠）、聴いてほしいポイント
