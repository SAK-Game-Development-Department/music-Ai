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
    "--exclude-module", "tkinter",
    "--distpath", str(ROOT / "dist"),
    "--workpath", str(ROOT / "build"),
    "--specpath", str(ROOT / "build"),
    str(ROOT / "packaging" / "launcher.py"),
]
print(" ".join(args))
subprocess.run(args, check=True)
print("\nBuild complete:", ROOT / "dist")
