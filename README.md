# music-Ai

音楽を作ってくれる高いAi

**AI（Claude）と一緒に、0 から曲を作る / 替え歌を作る**ためのツールキット。
曲はすべてテキスト（YAML）で表すので、人間も AI も読んで直せます。音源・MIDI・楽譜まで自動で書き出します。

## ダウンロードして使う（おすすめ・Python 不要）

[Releases](https://github.com/SAK-Game-Development-Department/music-Ai/releases) から自分のパソコン用のファイルをダウンロードして展開し、中のアプリをダブルクリックします。

| パソコン | ファイル | 起動するもの |
|---|---|---|
| Windows | `music-Ai-windows.zip` | `music-Ai.exe` |
| Mac（M1〜M4 など） | `music-Ai-mac-apple-silicon.zip` | `music-Ai` |
| Mac（Intel） | `music-Ai-mac-intel.zip` | `music-Ai` |
| Linux | `music-Ai-linux.tar.gz` | `./music-Ai` |

初回に「保護されました」「開発元を検証できません」と出たら、同梱の「はじめにお読みください.txt」を見てください（署名なしアプリのための表示です）。
曲は アプリと同じフォルダの `songs/`、書き出したファイルは `output/` に保存されます。

アプリは GitHub Actions（`.github/workflows/build-apps.yml`）で各 OS 向けに自動ビルドされます。
`v` で始まるタグ（例: `v0.2.0`）を push するか、Actions の build-apps を手動実行して release_tag にバージョンを入れると Releases に公開されます。手元でビルドする場合は `pip install pyinstaller` のあと `python packaging/build.py`（その OS 向けのファイルが `dist/` にできます）。

## ソースから使う（Python あり）

1. [Python](https://www.python.org/downloads/)（3.10 以上）をインストール
   - Windows はインストール時に **「Add python.exe to PATH」にチェック**
2. このフォルダの起動ファイルを**ダブルクリック**
   - Windows: `start_windows.bat`
   - Mac: `start_mac.command`（初回は右クリック →「開く」）
3. ブラウザにアプリ画面が開きます（初回だけ必要なライブラリを自動インストール）

| 画面 | できること |
|---|---|
| 🎼 **作曲** | キー・テンポ・アレンジを選び、パート（Aメロ/Bメロ/サビ…）ごとにコード進行と歌詞を入れて「作曲する」。歌詞のモーラ数はその場で表示。「2番」は前のパートと同じメロディで歌詞だけ変えられる |
| 🎤 **替え歌** | 元の曲を選び、新しい歌詞を書くだけ。元の文字数との差と、どう調整するかがその場で分かる。**YouTube の URL や音声ファイルからも取り込める**（テンポ・キー・コード・歌メロを自動で聴き取り、元の曲をカラオケ化して伴奏に）。**歌詞の自動生成**にも対応（ストーリー性あり／なし・テーマ選択） |
| 🎹 **編集・再生** | 伴奏付きで再生、ピアノロールと歌詞がカラオケのように進む。カラオケ版（ボーカルなし）、テンポ・アレンジ変更、MP3 / WAV / MIDI / 楽譜(MusicXML) / 歌詞のダウンロード |
| 📖 **音楽のきほん** | 定番コード進行の一覧（キーを選ぶとコード名に変換）、曲づくりのポイント |

**バージョン**（🎹 編集・再生タブ）: 「保存」は作業中の曲を上書きするだけです。節目の状態を残したいときは
「バージョンを保存」（メモは任意）。一覧から 2 つ選ぶと、歌詞の違いが行ごとに（追加・削除・変更で）見られます。
この機能には Git が必要です。入っていない場合やフォルダが Git 管理でない場合は「履歴機能は使えません」と表示され、ほかの機能はそのまま使えます。

アプリはこのパソコンの中だけで動きます（インターネットに曲は送られません）。
MP3 で保存するには ffmpeg が必要です（なくても WAV で再生・保存できます）。

<details>
<summary>コマンドで使う場合（上級者・AI 用）</summary>

```bash
pip install -r requirements.txt
python -m musicai app                                   # アプリ起動
python -m musicai compose specs/hajimari.yaml           # 作曲
python -m musicai kaeuta songs/hoshi.yaml --lyrics-file lyrics/ramen.yaml -o songs/ramen.yaml
python -m musicai validate songs specs                  # ファイル構造の検証（schemas/ に沿っているか）
python -m musicai migrate songs specs                   # 古い形式のファイルに schema_version を付ける
python -m musicai check songs/ramen.yaml                # 楽曲ルールの検証（先に validate も行う）
python -m musicai render songs/ramen.yaml               # → output/ に MP3・MIDI・楽譜
python -m musicai import "https://youtu.be/..." --start 45 --end 90   # YouTube / 音声ファイルを取り込む
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
start_windows.bat / start_mac.command   ソースからアプリ起動（ダブルクリック）
packaging/   exe などのビルド（launcher.py / build.py / 同梱の説明書）
musicai/
  app.py       アプリのサーバー（標準ライブラリのみ）
  web/         アプリ画面（HTML/CSS/JS）
  service.py   アプリと CLI 共通の処理
  theory.py    音名・キー・コード・ディグリー・定番進行
  lyrics.py    歌詞 → モーラ分割（かな / {漢字|よみ} / 英語）
  song.py      曲ファイル（YAML）の読み込み・検証
  schema.py    ファイル構造の検証（schemas/*.schema.json）
  migrate.py   古い形式のファイルを最新にする（schema_version）
  history.py   曲のバージョン履歴・歌詞の差分（git を使うのはここだけ）
  composer.py  歌詞 + 進行 → メロディ自動生成
  kaeuta.py    替え歌（歌詞差し替え + メロディ自動調整）
  lyricgen.py  歌詞の自動生成（音の数ぴったり・テーマ・ストーリー）
  transcribe.py 音源の聴き取り（テンポ・キー・コード・歌メロ）とカラオケ化
  audio_io.py  音声の読み書き（ffmpeg）と YouTube 取得（yt-dlp）
  arrange.py   伴奏の自動アレンジ（pop / ballad / rock / simple）
  synth.py     音源合成（母音で歌う仮歌シンセ + 楽器）
  export.py    MIDI / MusicXML / 歌詞カード
schemas/ 曲・作曲仕様の JSON Schema（人間・AI・CLI 共通の約束事）
songs/   保存した曲（アプリの曲リスト）
lyrics/  替え歌用の歌詞ファイル
specs/   作曲仕様（歌詞・進行・構成だけ書いたもの）
tests/   python -m unittest discover -s tests
```

## メモ

- 仮歌シンセは母音（あいうえお）で歌う簡易版です。歌詞をはっきり歌わせるには MusicXML を NEUTRINO / Synthesizer V などへ
- 既存曲の替え歌を公開する場合は元曲の権利に注意。サンプルはパブリックドメインのメロディ（きらきら星）+ オリジナル歌詞です

## ライセンス

このソフトウェア（コード・ドキュメント）は [MIT ライセンス](LICENSE) です。
サンプル曲の歌詞・メロディについては上の「メモ」を参照してください。既存曲を使った替え歌の権利は、このライセンスとは別です。
