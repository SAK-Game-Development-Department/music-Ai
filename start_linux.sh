#!/bin/bash
cd "$(dirname "$0")"
echo "music-Ai を起動しています..."
python3 -c "import numpy, yaml, yt_dlp, imageio_ffmpeg, pykakasi" 2>/dev/null || {
  echo "必要なライブラリをインストールします（初回、またはアップデート後のみ）..."
  python3 -m pip install --user -r requirements.txt
}
python3 -m musicai app
