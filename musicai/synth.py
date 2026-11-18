"""シンセサイザー: Arrangement を numpy で音声（WAV）にする。外部音源不要。

vocal は「母音で歌う」仮歌シンセ: 歌詞の母音（あいうえお）に合わせてフォルマントを変える。
本物の歌声にしたいときは MusicXML / MIDI を歌声合成ソフトへ。
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

from .arrange import Arrangement, Event

SR = 44100

# 母音フォルマント (F1, F2, F3) [Hz]
FORMANTS = {
    "a": (800, 1200, 2600),
    "i": (300, 2300, 3000),
    "u": (350, 1300, 2300),
    "e": (500, 1900, 2600),
    "o": (500, 850, 2500),
    "n": (280, 1000, 2300),
    "q": (400, 1200, 2400),
}


def mtof(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def _env(n: int, a: float, d: float, s: float, r: float, hold: int) -> np.ndarray:
    """ADSR。hold サンプル後に release。"""
    t = np.arange(n) / SR
    env = np.empty(n)
    a = max(a, 1e-4)
    att = t < a
    env[att] = t[att] / a
    dec = (~att)
    env[dec] = s + (1 - s) * np.exp(-(t[dec] - a) / max(d, 1e-4))
    if hold < n:
        rel_t = (np.arange(n - hold)) / SR
        env[hold:] = env[hold - 1 if hold > 0 else 0] * np.exp(-rel_t / max(r, 1e-4))
    return env


def voice(ev: Event, dur_s: float, prev_pitch: float | None, sec_per_beat: float) -> np.ndarray:
    rel = 0.12
    n = int((dur_s + rel) * SR)
    t = np.arange(n) / SR
    f0 = mtof(ev.pitch)
    # ポルタメント（前の音から滑らかに）
    if prev_pitch is not None and abs(prev_pitch - ev.pitch) < 12:
        glide = 0.06 if not ev.legato else 0.09
        ratio = 2 ** ((prev_pitch - ev.pitch) / 12)
        f = f0 * (1 + (ratio - 1) * np.exp(-t / (glide / 3)))
    else:
        f = np.full(n, f0)
    # ビブラート（伸ばした音だけ、遅れてかかる）
    vib_on = np.clip((t - 0.25) / 0.3, 0, 1) if dur_s > 0.4 else np.zeros(n)
    f = f * (1 + 0.012 * vib_on * np.sin(2 * np.pi * 5.6 * t))
    phase = 2 * np.pi * np.cumsum(f) / SR
    F = FORMANTS.get(ev.vowel, FORMANTS["a"])
    bw = (90, 120, 180)
    out = np.zeros(n)
    kmax = int(5000 / f0)
    for k in range(1, max(2, kmax)):
        fk = k * f0
        amp = 0.0
        for Fi, Bi, g in zip(F, bw, (1.0, 0.6, 0.25)):
            amp += g / (1 + ((fk - Fi) / Bi) ** 2)
        amp = (amp + 0.02) / (k ** 0.6)
        out += amp * np.sin(k * phase)
    # 息っぽさ
    noise = np.random.default_rng(int(ev.start * 100)).standard_normal(n) * 0.012
    out += noise
    att = 0.035 if not ev.legato else 0.01
    env = _env(n, att, 0.3, 0.85, rel / 2, int(dur_s * SR))
    if ev.vowel == "q":
        env *= 0.15
    return out * env * ev.vel


def piano(ev: Event, dur_s: float) -> np.ndarray:
    rel = 0.25
    n = int((dur_s + rel) * SR)
    t = np.arange(n) / SR
    f0 = mtof(ev.pitch)
    out = np.zeros(n)
    for k in range(1, 9):
        fk = f0 * k * (1 + 0.0004 * k * k)
        if fk > 12000:
            break
        out += (1 / k ** 1.3) * np.exp(-t * (1.2 + 0.6 * k) * (f0 / 260) ** 0.3) * np.sin(2 * np.pi * fk * t)
    hold = int(dur_s * SR)
    env = np.ones(n)
    env[:int(0.004 * SR)] = np.linspace(0, 1, int(0.004 * SR))
    env[hold:] *= np.exp(-np.arange(n - hold) / SR / 0.08)
    return out * env * ev.vel


def pad(ev: Event, dur_s: float) -> np.ndarray:
    rel = 0.6
    n = int((dur_s + rel) * SR)
    t = np.arange(n) / SR
    f0 = mtof(ev.pitch)
    out = np.zeros(n)
    for det in (-0.12, 0.0, 0.11):
        f = f0 * 2 ** (det / 12)
        for k in range(1, 12):
            if f * k > 6000:
                break
            out += (1 / k ** 1.4) * np.sin(2 * np.pi * f * k * t + det * 7 * k)
    env = _env(n, 0.35, 0.5, 0.8, rel / 3, int(dur_s * SR))
    return out * env * ev.vel * 0.35


def guitar(ev: Event, dur_s: float) -> np.ndarray:
    rel = 0.08
    n = int((dur_s + rel) * SR)
    t = np.arange(n) / SR
    f0 = mtof(ev.pitch)
    out = np.zeros(n)
    for k in range(1, 20):
        if f0 * k > 7000:
            break
        out += (1 / k) * np.sin(2 * np.pi * f0 * k * t * (1.002 if k % 2 else 1))
    out = np.tanh(out * 2.5) * 0.5
    env = _env(n, 0.003, 0.25, 0.6, rel / 2, int(dur_s * SR))
    return out * env * ev.vel


def bass(ev: Event, dur_s: float) -> np.ndarray:
    rel = 0.06
    n = int((dur_s + rel) * SR)
    t = np.arange(n) / SR
    f0 = mtof(ev.pitch)
    out = np.sin(2 * np.pi * f0 * t) + 0.35 * np.sin(4 * np.pi * f0 * t) + 0.12 * np.sin(6 * np.pi * f0 * t)
    out = np.tanh(out * 1.3)
    env = _env(n, 0.005, 0.4, 0.7, rel / 2, int(dur_s * SR))
    return out * env * ev.vel


_DRUM_CACHE: dict[int, np.ndarray] = {}


def drum(note: int) -> np.ndarray:
    if note in _DRUM_CACHE:
        return _DRUM_CACHE[note]
    rng = np.random.default_rng(note)
    if note == 36:  # kick
        n = int(0.35 * SR)
        t = np.arange(n) / SR
        f = 45 + 110 * np.exp(-t * 35)
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)
        x += 0.3 * rng.standard_normal(n) * np.exp(-t * 300)
        x *= 1.4
    elif note in (38, 37):  # snare / stick
        n = int(0.25 * SR)
        t = np.arange(n) / SR
        noise = rng.standard_normal(n)
        noise = np.diff(noise, prepend=0)
        if note == 38:
            x = 0.55 * noise * np.exp(-t * 18) + 0.6 * np.sin(2 * np.pi * 190 * t) * np.exp(-t * 25)
        else:
            x = 0.5 * np.sin(2 * np.pi * 900 * t) * np.exp(-t * 60) + 0.2 * noise * np.exp(-t * 80)
    elif note in (42, 46):  # hihat
        n = int((0.08 if note == 42 else 0.35) * SR)
        t = np.arange(n) / SR
        x = np.diff(np.diff(rng.standard_normal(n), prepend=0), prepend=0) * 0.25
        x *= np.exp(-t * (55 if note == 42 else 9))
    elif note == 49:  # crash
        n = int(1.6 * SR)
        t = np.arange(n) / SR
        x = np.diff(rng.standard_normal(n), prepend=0) * 0.35 * np.exp(-t * 2.2)
    else:  # toms
        n = int(0.3 * SR)
        t = np.arange(n) / SR
        base = 160 if note == 50 else 110
        f = base * (1 + 0.5 * np.exp(-t * 20))
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 10) * 0.9
    _DRUM_CACHE[note] = x
    return x


def _reverb_ir(seconds=1.6, decay=3.0) -> np.ndarray:
    n = int(seconds * SR)
    rng = np.random.default_rng(7)
    t = np.arange(n) / SR
    ir = rng.standard_normal((2, n)) * np.exp(-t * decay)
    ir[:, : int(0.012 * SR)] = 0
    return ir / np.sqrt((ir ** 2).sum(axis=1, keepdims=True))


def _fft_convolve(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    n = len(x) + len(h) - 1
    N = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(x, N) * np.fft.rfft(h, N), N)[:len(x)]


MIX = {
    # track: (gain, pan[-1..1], reverb send)
    "vocal": (0.55, 0.0, 0.28),
    "piano": (0.30, -0.25, 0.20),
    "pad": (0.22, 0.3, 0.35),
    "guitar": (0.20, 0.35, 0.12),
    "bass": (0.34, 0.0, 0.0),
    "drums": (0.50, 0.0, 0.08),
}


def render(arr: Arrangement, tempo: float, mute: set[str] | None = None, normalize: bool = True) -> np.ndarray:
    spb = 60.0 / tempo
    total = int((arr.total_beats * spb + 2.5) * SR)
    dry = np.zeros((2, total))
    wet_send = np.zeros((2, total))
    for track, events in arr.tracks.items():
        if mute and track in mute:
            continue
        gain, pan, send = MIX.get(track, (0.3, 0.0, 0.1))
        buf = np.zeros(total)
        prev_pitch = None
        prev_end = -1.0
        for ev in sorted(events, key=lambda e: e.start):
            s = int(ev.start * spb * SR)
            if s >= total:
                continue
            dur_s = ev.dur * spb
            if track == "vocal":
                pp = prev_pitch if abs(ev.start - prev_end) < 0.05 else None
                x = voice(ev, dur_s, pp, spb)
                prev_pitch = ev.pitch
                prev_end = ev.start + ev.dur
            elif track == "piano":
                x = piano(ev, dur_s)
            elif track == "pad":
                x = pad(ev, dur_s)
            elif track == "guitar":
                x = guitar(ev, dur_s)
            elif track == "bass":
                x = bass(ev, dur_s)
            elif track == "drums":
                x = drum(ev.pitch) * ev.vel
            else:
                continue
            e = min(total, s + len(x))
            buf[s:e] += x[: e - s]
        if track == "drums":
            # 少しだけ広げる
            pass
        l = np.cos((pan + 1) * np.pi / 4)
        r = np.sin((pan + 1) * np.pi / 4)
        dry[0] += buf * gain * l * 1.414
        dry[1] += buf * gain * r * 1.414
        if send:
            wet_send[0] += buf * gain * send
            wet_send[1] += buf * gain * send
    ir = _reverb_ir()
    wet = np.stack([_fft_convolve(wet_send[0], ir[0]), _fft_convolve(wet_send[1], ir[1])])
    mix = dry + wet * 0.9
    if not normalize:
        return mix
    # ソフトリミッター + ノーマライズ
    peak = np.max(np.abs(mix)) or 1.0
    mix = mix / peak * 1.25
    mix = np.tanh(mix) / np.tanh(1.25) * 0.89
    return mix


def write_wav(audio: np.ndarray, path: str | Path) -> None:
    data = (np.clip(audio, -1, 1) * 32767).astype("<i2").T.copy()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


def _ffmpeg() -> str:
    """ffmpeg の場所。exe の隣（または本体フォルダ）に ffmpeg.exe があればそれを使う。"""
    import shutil
    import sys

    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    for name in ("ffmpeg.exe", "ffmpeg"):
        if (base / name).is_file():
            return str(base / name)
    return shutil.which("ffmpeg") or "ffmpeg"


def wav_to_mp3(wav: str | Path, mp3: str | Path) -> bool:
    import sys

    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    try:
        subprocess.run([_ffmpeg(), "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "192k", str(mp3)],
                       check=True, creationflags=flags)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
