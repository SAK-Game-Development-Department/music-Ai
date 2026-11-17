# music-Ai

音楽を作ってくれる高いAi

**AI（Claude）と一緒に、0 から曲を作る / 替え歌を作る**ためのツールキット。
曲はすべてテキスト（YAML）で表すので、人間も AI も読んで直せます。音源・MIDI・楽譜まで自動で書き出します。

## 使い方（アプリ）

1. [Python](https://www.python.org/downloads/)（3.10 以上）をインストール
   - Windows はインストール時に **「Add python.exe to PATH」にチェック**
2. このフォルダの起動ファイルを**ダブルクリック**
   - Windows: `start_windows.bat`
   - Mac: `start_mac.command`（初回は右クリック →「開く」）
3. ブラウザにアプリ画面が開きます（初回だけ必要なライブラリを自動インストール）

| 画面 | できること |
|---|---|
| 🎼 **作曲** | キー・テンポ・アレンジを選び、パート（Aメロ/Bメロ/サビ…）ごとにコード進行と歌詞を入れて「作曲する」。歌詞のモーラ数はその場で表示。「2番」は前のパートと同じメロディで歌詞だけ変えられる |
| 🎤 **替え歌** | 元の曲を選び、新しい歌詞を書くだけ。元の文字数との差と、どう調整するかがその場で分かる |
| 🎹 **編集・再生** | 伴奏付きで再生、ピアノロールと歌詞がカラオケのように進む。カラオケ版（ボーカルなし）、テンポ・アレンジ変更、MP3 / WAV / MIDI / 楽譜(MusicXML) / 歌詞のダウンロード |
| 📖 **音楽のきほん** | 定番コード進行の一覧（キーを選ぶとコード名に変換）、曲づくりのポイント |

アプリはこのパソコンの中だけで動きます（インターネットに曲は送られません）。
MP3 で保存するには ffmpeg が必要です（なくても WAV で再生・保存できます）。

<details>
<summary>コマンドで使う場合（上級者・AI 用）</summary>

```bash
pip install -r requirements.txt
python -m musicai app                                   # アプリ起動
python -m musicai compose specs/hajimari.yaml           # 作曲
python -m musicai kaeuta songs/hoshi.yaml --lyrics-file lyrics/ramen.yaml -o songs/ramen.yaml
python -m musicai render songs/ramen.yaml               # → output/ に MP3・MIDI・楽譜
python -m musicai mora "きょうはいいてんき"              # モーラを数える
python -m musicai progressions --key G                  # 定番進行
```
</details>

`examples/` に書き出し済みのサンプル（MP3・MIDI・MusicXML）があります。

## ドキュメント

1. [音楽の作り方](docs/01_音楽の作り方.md) — 理論の基本（キー・コード・メロディ・構成・モーラ）。ツールの土台
2. [替え歌の作り方](docs/02_替え歌の作り方.md) — 替え歌の手順と自動調整ルール
3. [AI と曲を作るワークフロー](docs/03_AIと曲を作るワークフロー.md) — 0 から 1 曲作る流れ、Claude への頼み方

## 構成

```
start_windows.bat / start_mac.command   アプリ起動（ダブルクリック）
musicai/
  app.py       アプリのサーバー（標準ライブラリのみ）
  web/         アプリ画面（HTML/CSS/JS）
  service.py   アプリと CLI 共通の処理
  theory.py    音名・キー・コード・ディグリー・定番進行
  lyrics.py    歌詞 → モーラ分割（かな / {漢字|よみ} / 英語）
  song.py      曲ファイル（YAML）の読み込み・検証
  composer.py  歌詞 + 進行 → メロディ自動生成
  kaeuta.py    替え歌（歌詞差し替え + メロディ自動調整）
  arrange.py   伴奏の自動アレンジ（pop / ballad / rock / simple）
  synth.py     音源合成（母音で歌う仮歌シンセ + 楽器）
  export.py    MIDI / MusicXML / 歌詞カード
songs/   保存した曲（アプリの曲リスト）
lyrics/  替え歌用の歌詞ファイル
specs/   作曲仕様（歌詞・進行・構成だけ書いたもの）
tests/   python -m unittest discover -s tests
```

## メモ

- 仮歌シンセは母音（あいうえお）で歌う簡易版です。歌詞をはっきり歌わせるには MusicXML を NEUTRINO / Synthesizer V などへ
- 既存曲の替え歌を公開する場合は元曲の権利に注意。サンプルはパブリックドメインのメロディ（きらきら星）+ オリジナル歌詞です
