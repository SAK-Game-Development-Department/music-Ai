"""音源（YouTube やファイル）から曲データを起こす: テンポ・キー・コード・歌メロ。

外部の AI モデルを使わない軽量版（numpy のみ）:
  1. 中央定位の強調 … ボーカルは普通ステレオの真ん中にいるので、左右で差の大きい成分を弱める
  2. 歌メロ … 倍音を足し合わせる「ハーモニック・サリエンス」で各瞬間の一番目立つ音の高さを推定
  3. テンポ … 音の立ち上がり（オンセット）の周期を自己相関で求め、拍の位置を合わせる
  4. 音符化 … 音の高さの変化と立ち上がりで区切り、16 分音符のグリッドに量子化、キーの音階に寄せる
  5. キー / コード … クロマ（12 音の強さ）をテンプレートと照合
  6. カラオケ音源 … 中央成分（ボーカル帯域）を引いた簡易カラオケ

demucs（pip install demucs）が入っていれば、ボーカル分離に使って精度を上げる。
精度は完璧ではないので、結果はピアノロールで確認して、必要なら直す前提。
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import numpy as np

from .audio_io import istft, load_audio, save_wav, stft
from .theory import Key, parse_chord, pc_name

SR = 22050
N_FFT = 4096
HOP = 256  # 約 11.6ms
FPS = SR / HOP

MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


@dataclass
class Analysis:
    tempo: float
    t0: float  # 1 小節目の頭（秒、解析範囲の先頭から）
    key: Key
    notes: list[tuple[int, int, int]]  # (開始16分, 長さ16分, MIDI) 1 小節目の頭から
    chords: list[str]  # 小節ごと（"C" や "C G"）
    bars: int
    f0: np.ndarray = field(repr=False, default=None)
    log: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 前処理
def center_emphasis(L: np.ndarray, R: np.ndarray, power: float = 3.0, n_fft: int = N_FFT) -> tuple[np.ndarray, np.ndarray]:
    """(中央成分の振幅スペクトル, マスク) を返す。モノラルならマスク 1。"""
    XL, XR = stft(L, n_fft, HOP), stft(R, n_fft, HOP)
    mL, mR = np.abs(XL), np.abs(XR)
    sim = 1 - np.abs(XL - XR) / (mL + mR + 1e-9)
    mask = np.clip(sim, 0, 1) ** power
    return (mL + mR) * 0.5 * mask, mask


def demucs_available() -> bool:
    if getattr(sys, "frozen", False):
        return False
    try:
        import demucs  # noqa: F401
        return True
    except Exception:
        return False


def separate_demucs(path: Path, out_dir: Path) -> tuple[Path, Path] | None:
    """demucs で (vocals.wav, no_vocals.wav)。使えなければ None。"""
    if not demucs_available():
        return None
    try:
        subprocess.run([sys.executable, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs",
                        "-o", str(out_dir), str(path)], check=True, capture_output=True)
    except Exception:
        return None
    hits = list(out_dir.rglob("vocals.wav"))
    if not hits:
        return None
    voc = hits[0]
    return voc, voc.with_name("no_vocals.wav")


# ---------------------------------------------------------------- 歌メロの高さ
CAND = np.arange(45.0, 86.0, 0.25)  # A2〜C#6、1/4 半音刻み
HARM = 10


def salience(mag: np.ndarray) -> np.ndarray:
    """倍音サリエンス (候補数, フレーム)。"""
    bin_hz = SR / N_FFT
    m = np.sqrt(mag)  # 圧縮
    sal = np.zeros((len(CAND), mag.shape[1]), dtype=np.float32)
    f0 = 440.0 * 2 ** ((CAND - 69) / 12)
    nb = mag.shape[0]
    first = None
    upper = None
    odd = np.zeros((len(CAND), mag.shape[1]), dtype=np.float32)
    even = np.zeros_like(odd)
    for h in range(1, HARM + 1):
        b = np.round(f0 * h / bin_hz).astype(int)
        ok = b < nb - 1
        if not ok.any():
            break
        w = 0.84 ** (h - 1)
        bb = np.clip(b, 1, nb - 2)
        v = np.maximum(np.maximum(m[bb - 1], m[bb]), m[bb + 1])
        sal += (w * v * ok[:, None]).astype(np.float32)
        if h <= 6:
            if h % 2:
                odd += v * ok[:, None]
            else:
                even += v * ok[:, None]
        if h == 1:
            first = v
        elif h in (2, 3):
            upper = v if upper is None else np.maximum(upper, v)
    # 基音が弱い候補は「本当の音の 1/2・1/3 の高さ（下の倍音違い）」の疑いがあるので弱める
    fund_ratio = np.clip(first / (0.6 * upper + 1e-9), 0.25, 1.0)
    # 奇数倍音（1・3・5 倍）がほとんど無い候補は「本当の音の 1 オクターブ下」の誤り
    odd_ratio = np.clip(odd / (0.55 * even + 1e-9), 0.3, 1.0)
    return sal * (fund_ratio * odd_ratio).astype(np.float32)


def track_pitch(mag: np.ndarray, jump_cost: float = 0.07) -> tuple[np.ndarray, np.ndarray]:
    """フレームごとの MIDI 音高（無声は nan）と、その音高の強さ。

    各フレームで一番強い候補を独立に選ぶと伴奏やオクターブ違いに飛びやすいので、
    「強さの合計 − 音高の跳躍コスト」が最大になる経路を動的計画法（ビタビ）で求める。
    """
    lo_bin = int(80 / (SR / N_FFT))
    m = mag.copy()
    m[:lo_bin] = 0  # ベース帯を除外
    sal = salience(m)
    n_c, n_f = sal.shape
    peak_raw = sal.max(axis=0)
    norm = sal / (peak_raw[None, :] + 1e-9)
    # 1 オクターブ上の誤り対策: 1 オクターブ下にも同じくらい強い候補があれば下を選ぶ
    # （下側が「本当の音の 1 オクターブ下」の誤りなら、salience の奇数倍音チェックで既に弱まっている）
    down = np.zeros_like(norm)
    down[48:] = norm[:-48]
    norm = np.where((down >= 0.85 * norm) & (CAND[:, None] >= 67), norm * 0.85, norm)
    # 歌メロとしては低すぎる音域（G3 未満）は、ベースの倍音と紛れやすいので少し弱める
    low_w = np.clip(1 - (55 - CAND) * 0.04, 0.55, 1.0)
    norm = norm * low_w[:, None]
    step = CAND[1] - CAND[0]
    dist = np.abs(np.arange(n_c)[:, None] - np.arange(n_c)[None, :]) * step  # 半音
    trans = -jump_cost * np.minimum(dist, 12)
    score = norm[:, 0].copy()
    back = np.zeros((n_f, n_c), dtype=np.int16)
    for t in range(1, n_f):
        tot = score[None, :] + trans  # [to, from]
        bi = tot.argmax(axis=1)
        back[t] = bi
        score = tot[np.arange(n_c), bi] + norm[:, t]
    path = np.empty(n_f, dtype=int)
    path[-1] = int(score.argmax())
    for t in range(n_f - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    midi = CAND[path].astype(float)
    strength = sal[path, np.arange(n_f)]
    # 有声判定（ヒステリシス）: 強い所で歌い始め、少し弱くなっても続いている間は歌とみなす
    p35, p90 = np.percentile(peak_raw, 35), np.percentile(peak_raw, 90)
    hi_thr = p35 + 0.25 * (p90 - p35)
    lo_thr = p35 + 0.02 * (p90 - p35)
    above = strength > lo_thr
    v = np.zeros(n_f, dtype=bool)
    i = 0
    while i < n_f:
        if not above[i]:
            i += 1
            continue
        j = i
        while j < n_f and above[j]:
            j += 1
        if strength[i:j].max() > hi_thr:
            v[i:j] = True
        i = j
    # 30ms 未満の有声/無声の切り替わりは無視
    v = np.convolve(v.astype(float), np.ones(3) / 3, mode="same") > 0.5
    midi[~v] = np.nan
    return midi, strength


# ---------------------------------------------------------------- テンポ
N_FFT_SHORT = 1024


def onset_envelope(mag: np.ndarray, lo_hz=0, hi_hz=SR / 2, n_fft: int = N_FFT_SHORT) -> np.ndarray:
    """mag は短い窓（N_FFT_SHORT）の振幅スペクトル。"""
    bin_hz = SR / n_fft
    a, b = int(lo_hz / bin_hz), int(hi_hz / bin_hz)
    lm = np.log1p(100 * mag[a:b])
    flux = np.maximum(0, np.diff(lm, axis=1, prepend=lm[:, :1])).sum(axis=0)
    flux -= np.convolve(flux, np.ones(31) / 31, mode="same")  # ゆっくりした変化を除去
    return np.maximum(flux, 0)


def estimate_tempo(env: np.ndarray, lo=70, hi=180) -> float:
    e = env - env.mean()
    n = len(e)
    ac = np.fft.irfft(np.abs(np.fft.rfft(e, 2 * n)) ** 2)[:n]
    best, best_s = 120.0, -1e18
    for bpm in np.arange(lo, hi + 0.01, 0.25):
        lag = 60 * FPS / bpm
        s = 0.0
        for mult, w in ((1, 1.0), (2, 0.5), (4, 0.25), (0.5, 0.3)):
            l = lag * mult
            if l < n - 1:
                i = int(l)
                frac = l - i
                s += w * ((1 - frac) * ac[i] + frac * ac[i + 1])
        s *= np.exp(-0.5 * (np.log2(bpm / 115) / 0.9) ** 2)  # 115 付近をやや優先
        if s > best_s:
            best, best_s = bpm, s
    return float(best)


def refine_tempo(env: np.ndarray, tempo: float) -> tuple[float, float]:
    """テンポを ±1.5% の範囲で細かく探し、拍の位置と一緒に決める。曲が長いほど小さなズレが効くため。"""
    best = (tempo, 0.0, -1.0)
    sm = np.convolve(env, np.ones(3), mode="same")
    for bpm in np.arange(tempo * 0.985, tempo * 1.015, 0.02):
        period = 60 * FPS / bpm
        n_beats = int((len(env) - period) / period)
        if n_beats < 4:
            continue
        for ph in np.arange(0, period, 1.0):
            idx = (ph + period * np.arange(n_beats)).astype(int)
            s = sm[idx].sum()
            if s > best[2]:
                best = (bpm, ph, s)
    return round(float(best[0]), 2), best[1] / FPS


def beat_phase(env: np.ndarray, tempo: float) -> float:
    """最初の拍の位置（秒）。"""
    period = 60 * FPS / tempo
    best, best_s = 0.0, -1.0
    for ph in np.arange(0, period, 0.5):
        idx = (ph + period * np.arange(int((len(env) - ph) / period))).astype(int)
        s = env[idx].sum()
        if s > best_s:
            best, best_s = ph, s
    return best / FPS


# ---------------------------------------------------------------- クロマ・キー・コード
def chroma(mag: np.ndarray, lo_hz=60, hi_hz=2500) -> np.ndarray:
    bin_hz = SR / N_FFT
    freqs = np.arange(mag.shape[0]) * bin_hz
    sel = (freqs >= lo_hz) & (freqs <= hi_hz)
    pcs = (np.round(12 * np.log2(freqs[sel] / 440.0)) + 69).astype(int) % 12
    out = np.zeros((12, mag.shape[1]))
    m = np.sqrt(mag[sel])
    for pc in range(12):
        out[pc] = m[pcs == pc].sum(axis=0)
    return out


def estimate_key(ch_total: np.ndarray, melody_pcs: np.ndarray) -> Key:
    v = ch_total / (ch_total.sum() + 1e-9) + 0.5 * melody_pcs / (melody_pcs.sum() + 1e-9)
    best, best_s = Key(0, "major"), -2
    for t in range(12):
        for mode, prof in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
            s = np.corrcoef(v, np.roll(prof, t))[0, 1]
            if s > best_s:
                best, best_s = Key(t, mode), s
    return best


def refine_key_by_chords(key: Key, chords: list[str]) -> Key:
    """コードがすべてその調の音階に入るか・主和音の多さで、近い調（平行調・属調・下属調）と比べ直す。"""
    names = [c for bar in chords for c in bar.split()]
    if not names:
        return key
    parsed = [parse_chord(c) for c in names]
    cands = {key, Key((key.tonic + 7) % 12, key.mode), Key((key.tonic + 5) % 12, key.mode),
             Key((key.tonic + 9) % 12, "minor") if key.mode == "major" else Key((key.tonic + 3) % 12, "major")}

    def score(k: Key):
        sc = set(k.scale_pcs)
        diat = sum(all(pc in sc for pc in ch.pcs) for ch in parsed) / len(parsed)
        tonic = sum(ch.root == k.tonic for ch in parsed) / len(parsed)
        end = 0.1 if parsed[-1].root == k.tonic else 0.0
        return diat + 0.5 * tonic + end + (0.05 if k == key else 0)

    return max(cands, key=score)


def _chord_templates(key: Key):
    out = []
    diat = set(key.scale_pcs)
    for r in range(12):
        for q, iv in (("", (0, 4, 7)), ("m", (0, 3, 7))):
            t = np.zeros(12)
            t[[(r + i) % 12 for i in iv]] = 1
            t[r] += 0.3
            bonus = 0.04 if all((r + i) % 12 in diat for i in iv) else 0.0
            out.append((pc_name(r, key.prefer_flat) + q, r, t / np.linalg.norm(t), bonus))
    return out


def estimate_chords(ch: np.ndarray, bass: np.ndarray, frame_of, bars: int, bpb: int, key: Key) -> list[str]:
    tmpls = _chord_templates(key)

    def best_for(a, b):
        if b <= a:
            return None
        v = ch[:, a:b].sum(axis=1)
        bv = bass[:, a:b].sum(axis=1)
        if v.sum() < 1e-6:
            return None
        v = v / np.linalg.norm(v)
        bv = bv / (bv.max() + 1e-9)
        scores = [(float(v @ t) + bonus + 0.15 * bv[r], nm) for nm, r, t, bonus in tmpls]
        return max(scores)[1]

    out = []
    prev = None
    for b in range(bars):
        s, m, e = frame_of(b * bpb), frame_of(b * bpb + bpb / 2), frame_of((b + 1) * bpb)
        whole = best_for(s, e)
        h1, h2 = best_for(s, m), best_for(m, e)
        if h1 and h2 and h1 != h2 and whole in (h1, h2):
            name = f"{h1} {h2}"
        else:
            name = whole or prev or pc_name(key.tonic) + ("m" if key.mode == "minor" else "")
        out.append(name)
        prev = name.split()[-1]
    return out


# ---------------------------------------------------------------- 音符化
def harmonic_energy(mag_short: np.ndarray, midi: np.ndarray, n_harm: int = 6) -> np.ndarray:
    """短い窓のスペクトルで、推定した音高の倍音だけのエネルギー（音節の切れ目が見える）。"""
    bin_hz = SR / N_FFT_SHORT
    n = min(len(midi), mag_short.shape[1])
    out = np.zeros(len(midi))
    f0 = 440.0 * 2 ** ((np.nan_to_num(midi[:n], nan=60) - 69) / 12)
    cols = np.arange(n)
    nb = mag_short.shape[0]
    for h in range(1, n_harm + 1):
        b = np.clip(np.round(f0 * h / bin_hz).astype(int), 0, nb - 1)
        out[:n] += np.sqrt(mag_short[b, cols])
    out[np.isnan(midi)] = 0
    return out


def reattacks(strength: np.ndarray, midi: np.ndarray, rise: float = 1.35, look: int = 6) -> set[int]:
    """歌メロ自身の強さの「いったん下がって、また上がる」点 = 同じ高さで歌い直した音節の頭。"""
    n = len(strength)
    out = set()
    s = np.convolve(strength, np.ones(3) / 3, mode="same")
    last = -100
    for i in range(look, n - 2):
        if np.isnan(midi[i]):
            continue
        lo = s[i - look:i].min()
        if s[i] > rise * lo and s[i] >= s[i - 1] and s[i] >= s[i + 1] and i - last > look:
            # 谷が本当にあった（直前で下がっていた）か
            if s[i - look:i].argmin() > 0:
                out.add(int(i - look + s[i - look:i].argmin() + 1))
                last = i
    return out


def segment_notes(midi: np.ndarray, peaks: set[int], sec_per_16: float, t0: float, key: Key,
                  min_frames: int = 5) -> list[tuple[int, int, int]]:
    """フレーム音高 → 量子化した音符 [(開始16分, 長さ16分, MIDI)]（t0 からの位置）。

    peaks: 同じ高さのまま区切る位置（歌い直し）のフレーム番号。
    """
    n = len(midi)
    segs = []
    i = 0
    while i < n:
        if np.isnan(midi[i]):
            i += 1
            continue
        j = i
        cur = [midi[i]]
        start = i
        while j + 1 < n and not np.isnan(midi[j + 1]):
            nxt = midi[j + 1]
            ref = np.median(cur[-6:])
            jump = abs(nxt - ref) > 0.75
            stable_jump = jump and j + 3 < n and all(
                not np.isnan(midi[j + k]) and abs(midi[j + k] - nxt) < 0.6 for k in range(1, 4))
            onset_cut = (j + 1) in peaks and (j + 1 - start) >= min_frames
            if (stable_jump or onset_cut) and (j + 1 - start) >= min_frames:
                segs.append((start, j + 1, float(np.median(cur))))
                start = j + 1
                cur = []
            cur.append(nxt)
            j += 1
        if j + 1 - start >= min_frames:
            segs.append((start, j + 1, float(np.median(cur))))
        i = j + 1

    scale = set(key.scale_pcs)
    notes = []
    for a, b, p in segs:
        ta, tb = a / FPS - t0, b / FPS - t0
        qa, qb = round(ta / sec_per_16), round(tb / sec_per_16)
        if qb <= qa:
            if (tb - ta) < sec_per_16 * 0.45:
                continue
            qb = qa + 1
        pr = int(round(p))
        if pr % 12 not in scale:
            for cand in (pr - 1, pr + 1):
                if cand % 12 in scale and abs(cand - p) < 0.75:
                    pr = cand
                    break
        notes.append([qa, qb, pr])
    # 重なり解消・負の位置を除去
    out = []
    for a, b, p in sorted(notes):
        if out and a < out[-1][1]:
            if a <= out[-1][0]:
                continue
            out[-1][1] = a
        if b <= a:
            continue
        out.append([a, b, p])
    # 短い隙間（8 分音符以下）は前の音を伸ばして埋める（歌はレガート。子音で一瞬途切れるだけ）
    for k in range(len(out) - 1):
        gap = out[k + 1][0] - out[k][1]
        if 0 < gap <= 2:
            out[k][1] = out[k + 1][0]
    return [(a, b - a, p) for a, b, p in out if a >= 0]


# ---------------------------------------------------------------- 全体
def analyze(path: str | Path, start: float = 0.0, end: float | None = None, vocals_path: Path | None = None,
            progress=None) -> Analysis:
    def say(msg):
        if progress:
            progress(msg)

    say("音声を読み込んでいます…")
    x = load_audio(path, SR, start, end, channels=2)
    L, R = x[0], x[1]
    log = []
    say("テンポを調べています…")
    mono = (L + R) * 0.5
    mono_mag = np.abs(stft(mono, N_FFT, HOP))
    env = onset_envelope(np.abs(stft(mono, N_FFT_SHORT, HOP)))
    tempo = estimate_tempo(env)
    tempo, phase = refine_tempo(env, tempo)
    say(f"歌メロを聴き取っています…（テンポ {tempo:.0f}）")
    if vocals_path is not None:
        v = load_audio(vocals_path, SR, start, end, channels=1)[0]
        vmag = np.abs(stft(v, N_FFT, HOP))
        vshort = np.abs(stft(v, N_FFT_SHORT, HOP))
        log.append("ボーカル分離（demucs）を使いました")
    else:
        vmag, _ = center_emphasis(L, R)
        vshort, _ = center_emphasis(L, R, n_fft=N_FFT_SHORT)
        is_mono = np.allclose(L, R, atol=1e-4)
        log.append("モノラル音源のため中央強調なし" if is_mono else "中央定位を強調して歌メロを推定（簡易）")
    n = min(vmag.shape[1], mono_mag.shape[1])
    vmag, mono_mag, env = vmag[:, :n], mono_mag[:, :n], env[:n]
    midi, _ = track_pitch(vmag)
    peaks = reattacks(harmonic_energy(vshort, midi), midi)

    voiced_t = np.where(~np.isnan(midi))[0]
    if len(voiced_t) < FPS:
        raise ValueError("歌メロが見つかりませんでした（歌の入っている範囲を選んでください）")
    spb = 60 / tempo
    first_voice = voiced_t[0] / FPS
    # 1 小節目の頭: 拍の位置にそろえ、最初の歌の少し前
    beat0 = phase
    k = int(np.floor((first_voice - beat0) / spb))
    t0 = beat0 + max(0, k - (k % 4)) * spb
    if t0 > first_voice:
        t0 -= 4 * spb
    t0 = max(t0, beat0 % (4 * spb))
    sec16 = spb / 4

    # キー
    ch = chroma(mono_mag)
    mel_hist = np.zeros(12)
    for p in midi[~np.isnan(midi)]:
        mel_hist[int(round(p)) % 12] += 1
    key = estimate_key(ch.sum(axis=1), mel_hist)
    say(f"音符にしています…（キー {key.name()}）")
    notes = segment_notes(midi, peaks, sec16, t0, key)
    if not notes:
        raise ValueError("音符を取り出せませんでした")
    total_16 = max(a + d for a, d, _ in notes)
    bars = int(np.ceil(total_16 / 16)) or 1
    say("コードを調べています…")
    bass = chroma(mono_mag, 40, 250)
    frame_of = lambda beat: int(min(n, max(0, (t0 + beat * spb) * FPS)))
    chords = estimate_chords(ch, bass, frame_of, bars, 4, key)
    key2 = refine_key_by_chords(key, chords)
    if key2 != key:
        log.append(f"コードから調を {key.name()} → {key2.name()} に修正")
        key = key2
        chords = estimate_chords(ch, bass, frame_of, bars, 4, key)  # 表記（♯/♭）を合わせる
    log.append(f"テンポ {tempo:.1f} / キー {key.name()} / {bars} 小節 / 音符 {len(notes)} 個")
    return Analysis(tempo=round(float(tempo), 2), t0=float(t0), key=key, notes=notes, chords=chords, bars=bars, f0=midi, log=log)


def make_karaoke(path: str | Path, out: Path, start: float = 0.0, end: float | None = None, sr: int = 44100) -> Path:
    """中央のボーカル帯域を弱めた簡易カラオケ音源を作る。"""
    x = load_audio(path, sr, start, end, channels=2)
    L, R = x[0], x[1]
    n_fft, hop = 4096, 1024
    XL, XR = stft(L, n_fft, hop), stft(R, n_fft, hop)
    mL, mR = np.abs(XL), np.abs(XR)
    sim = np.clip(1 - np.abs(XL - XR) / (mL + mR + 1e-9), 0, 1)
    freqs = np.arange(XL.shape[0]) * sr / n_fft
    band = ((freqs > 180) & (freqs < 7000)).astype(float)[:, None]
    keep = 1 - 0.9 * band * sim ** 2
    yl = istft(XL * keep, n_fft, hop, len(L))
    yr = istft(XR * keep, n_fft, hop, len(R))
    y = np.stack([yl, yr])
    y /= max(1e-6, np.abs(y).max()) / 0.9
    save_wav(y, out, sr)
    return out


def analysis_to_song(an: Analysis, title: str, section_bars: int = 8) -> dict:
    """解析結果 → 曲 dict（セクションは section_bars 小節ごと）。"""
    from .song import Note, melody_to_text

    bpb = 4
    sections = {}
    structure = []
    notes = sorted(an.notes)
    for si, b0 in enumerate(range(0, an.bars, section_bars)):
        b1 = min(an.bars, b0 + section_bars)
        lo, hi = b0 * 16, b1 * 16
        seq: list[Note] = []
        pos = lo
        for a, d, p in notes:
            e = a + d
            if e <= lo or a >= hi:
                continue
            cont = a < lo  # 前のセクションから続く音
            a2, e2 = max(a, lo), min(e, hi)
            if a2 > pos:
                seq.append(Note(None, Fraction(a2 - pos, 4)))
            seq.append(Note(p, Fraction(e2 - a2, 4), melisma=cont))
            pos = e2
        if pos < hi:
            seq.append(Note(None, Fraction(hi - pos, 4)))
        name = f"パート{si + 1}"
        sec = {"chords": " | ".join(an.chords[b0:b1])}
        if any(not n.is_rest for n in seq):
            # 先頭がメリスマだと歌詞が付けられないので、通常の音に戻す
            for nn in seq:
                if not nn.is_rest:
                    nn.melisma = False
                    break
            sec["melody"] = melody_to_text(seq, bpb, an.key.prefer_flat)
        sections[name] = sec
        structure.append(name)
    return {
        "title": title,
        "key": an.key.name(),
        "tempo": an.tempo,
        "time": "4/4",
        "style": "pop",
        "structure": structure,
        "sections": sections,
    }
