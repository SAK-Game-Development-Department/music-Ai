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
    "--hidden-import", "musicai.app",
    # 音声のデコードに使う ffmpeg 本体（imageio-ffmpeg に同梱）と、YouTube 取得の yt-dlp
    "--collect-all", "imageio_ffmpeg",
    "--collect-submodules", "yt_dlp",
    "--exclude-module", "tkinter",
    "--distpath", str(ROOT / "dist"),
    "--workpath", str(ROOT / "build"),
    "--specpath", str(ROOT / "build"),
    str(ROOT / "packaging" / "launcher.py"),
]
print(" ".join(args))
try:
    import yt_dlp_ejs  # noqa: F401  YouTube の署名解決スクリプト（yt-dlp[default] に含まれる）

    args[-1:-1] = ["--collect-all", "yt_dlp_ejs"]
except ImportError:
    pass
subprocess.run(args, check=True)
print("\nBuild complete:", ROOT / "dist")
