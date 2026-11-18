"""生成 → 検証 → 書き出しを、1 回で実行する（失敗しても songs/ と output/ を汚さない）。

    作曲（または替え歌）→ validate（ファイル構造）→ check（警告ゼロ）→ 書き出し → 反映

途中までは、作業用の一時フォルダの中だけで行う。どこかで失敗したら、一時フォルダを捨てて終わり
（songs/ と output/ は 1 バイトも変わらない）。最後の「反映」で一時フォルダから本番のフォルダへ
入れ替えるときだけ、上書きされる既存のファイルを先に退避し、途中で失敗したら元に戻す（ロールバック）。

既存の曲を上書きするとき（overwrite: true）は、入れ替える前に、今の内容を自動でバージョンとして
残す（Git が使えるときだけ）。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import traceback
from pathlib import Path

import yaml

from . import service
from .history import History, HistoryError, HistoryUnavailable
from .schema import validate_data
from .tools import EXPORT_FORMATS, ToolError, _ensure_free, _rel, _warnings, compose_data, kaeuta_data

_lock = threading.Lock()
_AUDIO = {"wav", "mp3"}


class PipelineError(ToolError):
    """どの段階で失敗したか（step）と、そこまでの進み具合（steps）を持つ。"""

    def __init__(self, step: str, message: str, steps: list[str], rolled_back: bool = False):
        self.step, self.steps, self.rolled_back = step, list(steps), rolled_back
        done = "".join(f"\n  ✓ {s}" for s in steps)
        tail = "反映の途中で失敗したため、元の状態に戻しました。" if rolled_back else "songs/ と output/ は変更していません。"
        super().__init__(f"「{step}」で失敗しました: {message}\n{tail}" + (f"\n完了した段階:{done}" if done else ""))


def _commit(pairs: list[tuple[Path, Path]], backup_dir: Path) -> None:
    """(一時フォルダのファイル, 本番のパス) を入れ替える。途中で失敗したら、すべて元に戻して例外を投げ直す。"""
    backup_dir.mkdir(parents=True, exist_ok=True)
    done: list[tuple[Path, Path | None]] = []
    try:
        for i, (src, dst) in enumerate(pairs):
            dst.parent.mkdir(parents=True, exist_ok=True)
            backup = None
            if dst.exists():
                backup = backup_dir / f"{i}{dst.suffix}"
                shutil.copy2(dst, backup)  # 先に退避（入れ替えるまで、元のファイルはそのまま）
            os.replace(src, dst)
            done.append((dst, backup))
    except BaseException:
        for dst, backup in reversed(done):
            try:
                if backup is not None:
                    shutil.copy2(backup, dst)
                else:
                    dst.unlink(missing_ok=True)
            except OSError:
                traceback.print_exc(file=sys.stderr)
        raise


def run(args: dict) -> dict:
    """args: mode(compose|kaeuta) と、compose / kaeuta ツールと同じ入力、formats、allow_warnings、overwrite。"""
    from .song import song_from_dict

    steps: list[str] = []
    mode = args.get("mode")
    if mode not in ("compose", "kaeuta"):
        raise ToolError("mode は compose か kaeuta にしてください")
    formats = list(dict.fromkeys(args.get("formats") or ["midi", "musicxml", "lyrics"]))
    label = "作曲" if mode == "compose" else "替え歌"

    def fail(step, e, rolled_back=False):
        raise PipelineError(step, str(e), steps, rolled_back) from None

    # 1. 生成（まだ何も保存しない）
    try:
        if mode == "compose":
            name, data = compose_data(args)
            report: list[str] = []
        else:
            name, data, report = kaeuta_data(args)
        name = service.safe_name(name)
        _ensure_free(name, bool(args.get("overwrite")))
    except ValueError as e:
        fail(label, e)
    steps.append(label)

    # 2. validate（ファイル構造）
    text = service.dump_yaml(data)
    r = validate_data(yaml.safe_load(text), "song")
    if not r.ok:
        fail("検証（validate）", "曲の形式が正しくありません:\n" + r.format())
    steps.append("検証（validate）")

    # 3. check（警告ゼロ）
    try:
        song = song_from_dict(data)
    except ValueError as e:
        fail("検査（check）", f"曲として読めません: {e}")
    warns = _warnings(song)
    if warns and not args.get("allow_warnings"):
        fail("検査（check）", "警告があります（警告ゼロにしてください）:\n" + "\n".join("  " + w for w in warns))
    steps.append("検査（check）")

    song_dst = service.SONGS_DIR / f"{name}.yaml"
    overwriting = song_dst.exists()
    with _lock, tempfile.TemporaryDirectory(dir=service.DATA_DIR, prefix=".musicai-staging-") as td:
        stage = Path(td)
        # 4. 書き出し（一時フォルダの中だけ）
        try:
            (stage / "songs").mkdir()
            (stage / "songs" / f"{name}.yaml").write_text(text, encoding="utf-8")
            made = service.render_song(song, name, audio=bool(_AUDIO & set(formats)), out_dir=stage / "output")
        except Exception as e:  # noqa: BLE001 — どんな失敗でも、本番には何も出さない
            traceback.print_exc(file=sys.stderr)
            fail("書き出し", f"{type(e).__name__}: {e}")
        files = {f: made[f] for f in formats if f in made}
        missing = [f for f in formats if f not in files]
        steps.append("書き出し")

        # 5. 反映（上書きなら先に今の内容をバージョンとして残し、入れ替える。失敗したら元に戻す）
        snapshot = None
        if overwriting:
            try:
                r = History(service.SONGS_DIR).save_version(name, "自動作成の前の自動保存")
                snapshot = r["no"] if r["saved"] else None
            except HistoryError as e:
                if not isinstance(e, HistoryUnavailable):  # 履歴が使えないだけなら続ける
                    fail("反映", f"上書き前のバージョン保存に失敗したため中止しました: {e}")
        pairs = [(stage / "songs" / f"{name}.yaml", song_dst)] + [(stage / "output" / fn, service.OUTPUT_DIR / fn)
                                                                   for fn in files.values()]
        try:
            _commit(pairs, stage / "backup")
        except Exception as e:  # noqa: BLE001 — 元に戻す処理は _commit の中で済んでいる
            traceback.print_exc(file=sys.stderr)
            fail("反映", f"{type(e).__name__}: {e}", rolled_back=True)
        steps.append("反映")

    out = {"ok": True, "name": name, "path": _rel(song_dst), "steps": steps, "warnings": warns, "report": report,
           "files": {f: _rel(service.OUTPUT_DIR / fn) for f, fn in files.items()}, "snapshot_version": snapshot}
    if missing:
        out["note"] = "作れなかった形式: " + ", ".join(missing) + "（mp3 は ffmpeg が必要です）"
    return out
