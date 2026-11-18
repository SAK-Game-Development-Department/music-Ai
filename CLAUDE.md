# CLAUDE.md — このリポジトリで AI が曲作りを手伝うときの手順

ユーザーは日本語話者。返答は日本語で。目的は「AI と一緒に 0 から曲を作る」「替え歌を作る」。

## 前提知識
- `docs/01_音楽の作り方.md` の理論・ルールがコードの土台。作曲の相談ではこれに沿って理由を説明する
- 曲ファイル形式は `musicai/song.py` の docstring、作曲仕様は `docs/03_AIと曲を作るワークフロー.md`

## 曲を直すとき
1. `songs/*.yaml` を編集（melody: `音名:拍数`、`r`=休符、`~`=メリスマ、`|`=小節線）
2. `python -m musicai check songs/xxx.yaml` で 警告ゼロ・音符数=モーラ数 を確認
3. `python -m musicai render songs/xxx.yaml` で書き出し、mp3 をユーザーに渡す
4. 何をなぜ変えたか（理論的な理由）を短く説明する

## 新しい曲を作るとき
1. コンセプト（テーマ・雰囲気・テンポ・キー）をユーザーと決める
2. `specs/xxx.yaml` に構成・進行・歌詞を書く（歌詞は 1 行 = 1 フレーズ、漢字は `{漢字|よみ}`）
3. `python -m musicai compose specs/xxx.yaml` → `render`。seed 違いで複数案を出してもよい

## 替え歌
`python -m musicai kaeuta songs/元.yaml --lyrics-file 新歌詞.yaml -o songs/新.yaml`
既存曲（著作権のある曲）を扱う場合、公開時は権利者の許諾が必要になりうることを伝える。

## テスト
`python -m unittest discover -s tests`

## プロンプトテンプレート（`prompts/`）
AI に作曲・修正・レビューを頼むときは、次のテンプレートを渡す（どれも `schemas/*.json` と `schema_version: 1`、
出力形式、書き出し前の `validate` → `check`、歌詞の読み指定・melody 記法の規則を含む）。上の手順はそのまま有効。
- 新しい曲の作曲仕様を作る: `prompts/compose.md`
- 既存の曲を理論的な理由つきで直す: `prompts/revise.md`
- 曲を理論・モーラ数・スキーマの観点でレビューする: `prompts/review.md`

ファイル構造の検証は `python -m musicai validate <path>`、楽曲ルールの検証は `check`（`check` は先に `validate` を行う）。
スキーマ通過率の測り方は `docs/04_プロンプトの使い方と測定.md`。
