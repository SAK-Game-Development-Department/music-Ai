# music-Ai

音楽を作ってくれる高いAi

**AI（Claude）と一緒に、0 から曲を作る / 替え歌を作る**ためのツールキット。
曲はすべてテキスト（YAML）で表すので、人間も AI も読んで直せます。音源・MIDI・楽譜まで自動で書き出します。

## できること

| | コマンド |
|---|---|
| 🎼 歌詞とコード進行から**メロディを自動作曲** | `python -m musicai compose specs/hajimari.yaml` |
| 🎤 既存曲の**歌詞だけ替える（替え歌）**。モーラ数のズレを自動調整 | `python -m musicai kaeuta songs/hoshi.yaml --lyrics-file ...` |
| 🔊 伴奏（ドラム・ベース・ピアノ・パッド）を自動アレンジして **MP3/WAV** に | `python -m musicai render songs/xxx.yaml` |
| 📄 **MIDI**（歌詞付き）・**MusicXML**（歌声合成ソフト用）・歌詞カードを出力 | 同上 |
| 🔢 歌詞のモーラ数を数える | `python -m musicai mora "きょうはいいてんき"` |
| 🎹 定番コード進行（王道進行・カノン進行・小室進行…）の一覧 | `python -m musicai progressions --key G` |

## はじめかた

```bash
pip install -r requirements.txt     # numpy, pyyaml（MP3 出力には ffmpeg）

# 例1: 0 から作曲
python -m musicai compose specs/hajimari.yaml
python -m musicai render songs/hajimari.yaml          # → output/hajimari.mp3

# 例2: 替え歌（きらきら星のメロディ → ラーメンの歌）
python -m musicai kaeuta songs/hoshi.yaml --lyrics-file songs/hoshi_kaeuta_lyrics.yaml -o songs/ramen.yaml
python -m musicai render songs/ramen.yaml
```

`examples/` に書き出し済みのサンプル（MP3・MIDI・MusicXML）があります。

## ドキュメント

1. [音楽の作り方](docs/01_音楽の作り方.md) — 理論の基本（キー・コード・メロディ・構成・モーラ）。ツールの土台
2. [替え歌の作り方](docs/02_替え歌の作り方.md) — 替え歌の手順と自動調整ルール
3. [AI と曲を作るワークフロー](docs/03_AIと曲を作るワークフロー.md) — 0 から 1 曲作る流れ、Claude への頼み方

## 構成

```
musicai/
  theory.py    音名・キー・コード・ディグリー・定番進行
  lyrics.py    歌詞 → モーラ分割（かな / {漢字|よみ} / 英語）
  song.py      曲ファイル（YAML）の読み込み・検証
  composer.py  歌詞 + 進行 → メロディ自動生成
  kaeuta.py    替え歌（歌詞差し替え + メロディ自動調整）
  arrange.py   伴奏の自動アレンジ（pop / ballad / rock / simple）
  synth.py     音源合成（母音で歌う仮歌シンセ + 楽器）
  export.py    MIDI / MusicXML / 歌詞カード
specs/   作曲仕様（歌詞・進行・構成だけ書いたもの）
songs/   曲ファイル（メロディまで入ったもの）
tests/   python -m unittest discover -s tests
```

## メモ

- 仮歌シンセは母音（あいうえお）で歌う簡易版です。歌詞をはっきり歌わせるには MusicXML を NEUTRINO / Synthesizer V などへ
- 既存曲の替え歌を公開する場合は元曲の権利に注意。サンプルはパブリックドメインのメロディ（きらきら星）+ オリジナル歌詞です
