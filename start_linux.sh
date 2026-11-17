#!/bin/bash
cd "$(dirname "$0")"
echo "music-Ai を起動しています..."
python3 -c "import numpy, yaml" 2>/dev/null || {
  echo "初回のみ: 必要なライブラリをインストールします..."
  python3 -m pip install --user -r requirements.txt
}
python3 -m musicai app
