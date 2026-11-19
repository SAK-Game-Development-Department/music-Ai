"""exe をビルドする: python packaging/build.py  → dist/music-Ai(.exe)

Windows で実行すると music-Ai.exe、Mac/Linux ではそれぞれの実行ファイルができる。
（PyInstaller はビルドした OS 向けのファイルしか作れない）
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
args = [
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
    "--name", "music-Ai",
    "--paths", str(ROOT),
    "--add-data", f"{ROOT / 'musicai' / 'web'}:musicai/web",
    "--add-data", f"{ROOT / 'songs'}:songs",
    "--add-data", f"{ROOT / 'schemas'}:schemas",  # 曲データの形式チェックに使う
    "--hidden-import", "musicai.app",
    # 音声のデコードに使う ffmpeg 本体（imageio-ffmpeg に同梱）と、YouTube 取得の yt-dlp
    "--collect-all", "imageio_ffmpeg",
    "--collect-submodules", "yt_dlp",
    "--collect-all", "pykakasi",  # 原曲の歌詞（漢字）の読み
    "--exclude-module", "tkinter",
    "--distpath", str(ROOT / "dist"),
    "--workpath", str(ROOT / "build"),
    "--specpath", str(ROOT / "build"),
    str(ROOT / "packaging" / "launcher.py"),
]
print(" ".join(args))
try:
    import faster_whisper  # noqa: F401  Whisper（歌詞とタイミングの聴き取り）

    args[-1:-1] = ["--collect-all", "faster_whisper", "--collect-all", "ctranslate2", "--collect-all", "av",
                   "--collect-all", "tokenizers", "--hidden-import", "huggingface_hub"]
except ImportError:
    print("faster-whisper が入っていないので、Whisper なしでビルドします")
try:
    import yt_dlp_ejs  # noqa: F401  YouTube の署名解決スクリプト（yt-dlp[default] に含まれる）

    args[-1:-1] = ["--collect-all", "yt_dlp_ejs"]
except ImportError:
    pass
subprocess.run(args, check=True)
print("\nBuild complete:", ROOT / "dist")
