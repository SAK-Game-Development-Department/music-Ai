"""Whisper（OpenAI の音声認識モデル）で歌詞と、その歌われているタイミングを聴き取る。

使えるものを順に使う:
  1. faster-whisper … OpenAI の Whisper モデルを軽く速く動かす実装（アプリ版にも入れられる）
  2. openai-whisper … OpenAI 公式の実装（PyTorch が必要。入っていれば使う）
ソースから動かしていて、どちらも無いときは faster-whisper を自動でインストールする。
モデル（数百 MB〜）は初回だけインターネットからダウンロードされる。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

import numpy as np

MODELS = ("tiny", "base", "small", "medium", "large-v3")
DEFAULT_MODEL = "small"


class AsrUnavailable(RuntimeError):
    pass


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


def backend() -> str | None:
    """使える Whisper の実装名（なければ None）。"""
    try:
        import faster_whisper  # noqa: F401
        return "faster-whisper"
    except Exception:  # noqa: BLE001
        pass
    try:
        import whisper  # noqa: F401
        return "openai-whisper"
    except Exception:  # noqa: BLE001
        return None


def installable() -> bool:
    """自動でインストールできるか（ソースから動かしているとき）。"""
    return not getattr(sys, "frozen", False)


def ensure_backend(progress=None) -> str:
    name = backend()
    if name:
        return name
    if not installable():
        raise AsrUnavailable("このアプリには Whisper が入っていません")
    from .audio_io import AudioError, ensure_package

    try:
        ensure_package("faster_whisper", "faster-whisper", progress)
    except (AudioError, ImportError) as e:
        raise AsrUnavailable(f"Whisper（faster-whisper）をインストールできませんでした: {e}")
    return "faster-whisper"


_MODEL_CACHE: dict[tuple[str, str], object] = {}


def transcribe(audio16k: np.ndarray, model: str = DEFAULT_MODEL, prompt: str | None = None,
               progress=None) -> list[Segment]:
    """16kHz モノラルの音声 → 日本語の歌詞（行と、言葉ごとの時刻）。

    prompt に原曲の歌詞を渡すと、それに寄せて聴き取る（聴き間違いが減る）。
    """
    name = ensure_backend(progress)
    if model not in MODELS:
        model = DEFAULT_MODEL
    audio = np.ascontiguousarray(audio16k, dtype=np.float32)
    say = progress or (lambda m: None)
    prompt = (prompt or "")[:400] or None
    if name == "faster-whisper":
        from faster_whisper import WhisperModel

        key = (name, model)
        if key not in _MODEL_CACHE:
            say(f"Whisper のモデル（{model}）を準備しています…（初回はダウンロードに数分かかります）")
            _MODEL_CACHE[key] = WhisperModel(model, device="cpu", compute_type="int8")
        say("Whisper で歌詞を聴き取っています…（曲の長さによっては数分かかります）")
        segs, _info = _MODEL_CACHE[key].transcribe(
            audio, language="ja", word_timestamps=True, initial_prompt=prompt,
            condition_on_previous_text=False, vad_filter=False, beam_size=5)
        out = []
        for s in segs:
            words = [Word(float(w.start), float(w.end), w.word) for w in (s.words or [])]
            out.append(Segment(float(s.start), float(s.end), s.text, words))
        return out
    import whisper

    key = (name, model)
    if key not in _MODEL_CACHE:
        say(f"Whisper のモデル（{model}）を準備しています…（初回はダウンロードに数分かかります）")
        _MODEL_CACHE[key] = whisper.load_model(model)
    say("Whisper で歌詞を聴き取っています…（曲の長さによっては数分かかります）")
    res = _MODEL_CACHE[key].transcribe(audio, language="ja", word_timestamps=True, initial_prompt=prompt,
                                       condition_on_previous_text=False, fp16=False)
    out = []
    for s in res.get("segments", []):
        words = [Word(float(w["start"]), float(w["end"]), w["word"]) for w in s.get("words", [])]
        out.append(Segment(float(s["start"]), float(s["end"]), s["text"], words))
    return out
