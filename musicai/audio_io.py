"""音声ファイルの入出力と YouTube からの取得。

- デコード/エンコードは ffmpeg（imageio-ffmpeg 同梱版 → アプリ隣の ffmpeg → PATH の順に探す）
- YouTube 取得は yt-dlp。動画ではなく音声だけを取る
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class AudioError(RuntimeError):
    pass


def ffmpeg_exe() -> str:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    for name in ("ffmpeg.exe", "ffmpeg"):
        if (base / name).is_file():
            return str(base / name)
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    if not exe:
        raise AudioError("ffmpeg が見つかりません（pip install imageio-ffmpeg で入ります）")
    return exe


def load_audio(path: str | Path, sr: int = 22050, start: float = 0.0, end: float | None = None,
               channels: int = 2) -> np.ndarray:
    """音声ファイル → float32 配列 (channels, n)。start/end は秒。"""
    cmd = [ffmpeg_exe(), "-v", "error", "-nostdin"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(path)]
    if end is not None:
        cmd += ["-t", f"{max(0.1, end - start):.3f}"]
    cmd += ["-vn", "-f", "f32le", "-acodec", "pcm_f32le", "-ac", str(channels), "-ar", str(sr), "-"]
    p = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW)
    if p.returncode != 0:
        raise AudioError("音声を読み込めませんでした: " + p.stderr.decode("utf-8", "replace")[-300:])
    x = np.frombuffer(p.stdout, dtype="<f4")
    if x.size < sr * channels:
        raise AudioError("音声が短すぎるか、音が入っていません")
    return x.reshape(-1, channels).T.copy()


def save_wav(audio: np.ndarray, path: str | Path, sr: int) -> None:
    import wave

    a = np.atleast_2d(audio)
    data = (np.clip(a, -1, 1) * 32767).astype("<i2").T.copy()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(a.shape[0])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())


def is_url(text: str) -> bool:
    return bool(re.match(r"https?://", (text or "").strip()))


def download_audio(url: str, out_dir: Path, progress=None) -> tuple[Path, str]:
    """yt-dlp で音声だけをダウンロード。(ファイル, タイトル) を返す。"""
    try:
        import yt_dlp
    except ImportError:
        raise AudioError("yt-dlp が入っていません（pip install yt-dlp）")
    out_dir.mkdir(parents=True, exist_ok=True)

    def hook(d):
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                progress(f"ダウンロード中… {d.get('downloaded_bytes', 0) * 100 // total}%")

    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
        "ffmpeg_location": ffmpeg_exe(),
        "max_filesize": 200 * 1024 * 1024,
        # YouTube の署名解決に使える JS ランタイムがあれば使う（deno / node / bun）
        "js_runtimes": {"deno": {}, "node": {}, "bun": {}},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info.get("_type") == "playlist" and info.get("entries"):
                info = info["entries"][0]
            path = Path(ydl.prepare_filename(info))
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        raise AudioError(
            "動画から音声を取得できませんでした。URL が正しいか確認してください。"
            " 何度も失敗する場合は、yt-dlp の更新（pip install -U yt-dlp）か、"
            "音声ファイル（mp3 / m4a / wav）を直接選んでください。\n詳細: " + msg[-300:])
    if not path.exists():
        cands = sorted(out_dir.glob("source.*"))
        if not cands:
            raise AudioError("ダウンロードしたファイルが見つかりません")
        path = cands[0]
    return path, info.get("title") or "imported"


# ---------------- STFT ----------------
def stft(x: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    """x: (n,) → 複素スペクトル (bins, frames)。中心揃え。"""
    pad = n_fft // 2
    xp = np.pad(x, (pad, pad + n_fft))
    n_frames = 1 + (len(xp) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n_frames)[:, None]
    win = np.hanning(n_fft).astype(np.float32)
    frames = xp[idx] * win
    return np.fft.rfft(frames, axis=1).T


def istft(X: np.ndarray, n_fft: int, hop: int, length: int) -> np.ndarray:
    win = np.hanning(n_fft)
    frames = np.fft.irfft(X.T, n=n_fft, axis=1) * win
    n = n_fft + hop * (frames.shape[0] - 1)
    out = np.zeros(n)
    norm = np.zeros(n)
    for i, f in enumerate(frames):
        s = i * hop
        out[s:s + n_fft] += f
        norm[s:s + n_fft] += win ** 2
    out /= np.maximum(norm, 1e-6)
    pad = n_fft // 2
    return out[pad:pad + length]
