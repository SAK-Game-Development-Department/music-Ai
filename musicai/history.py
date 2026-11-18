"""曲のバージョン履歴（保存の履歴・歌詞の差分）。

git を呼ぶのはこのモジュールだけ。他のモジュールには「バージョン」「メモ」「版番号」しか見せない。

- 履歴の単位は曲（songs/<name>.yaml）ごと。版番号は 1 から始まる連番で、ハッシュは外に出さない。
- 「保存」（ファイルを上書きするだけ）と違い、「バージョン保存」だけが履歴に載る。
  内部ではその曲のファイルだけを指定してコミットする（ほかの変更・staged のファイルを巻き込まない）。
- アプリが作ったコミットには印（Musicai-Version と、曲のパスを示す Musicai-Song）を付け、
  一覧にはその曲の印のあるものだけを出す。開発用のコミットが曲ファイルを触っていても、バージョンとしては
  出ない。ファイルが開発用コミットから変わっていない状態でも、最初のバージョンを作れる。
- 別名で保存した曲は新しい曲として、履歴も 1 から始まる。
- 一覧・差分はコミット印の種類（kind）ごとに引ける作りにしてあり、後から「提案」用の版（C3）を
  別の印で足せる。

git が無い・リポジトリの外などの場合は HistoryUnavailable（= 履歴機能は使えません）になる。
"""
from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import yaml

UNAVAILABLE_MESSAGE = "履歴機能は使えません"
KIND_VERSION = "Musicai-Version"  # 将来 Musicai-Proposal などを足せる
SONG_TRAILER = "Musicai-Song"
_DEFAULT_NOTE = "バージョン保存"
_TIMEOUT = 20
_lock = threading.Lock()


class HistoryError(ValueError):
    """利用者に見せてよい（git の用語を含まない）エラー。"""


class HistoryUnavailable(HistoryError):
    def __init__(self, message: str = UNAVAILABLE_MESSAGE):
        super().__init__(message)


@dataclass
class Version:
    no: int          # 曲ごとの連番（1 から）
    at: str          # 保存した日時（ISO 8601、ローカル時刻）
    note: str        # メモ（空もある）
    summary: str     # 前のバージョンからの変更概要
    kind: str = KIND_VERSION

    def to_dict(self) -> dict:
        return {"no": self.no, "at": self.at, "note": self.note, "summary": self.summary}


class History:
    def __init__(self, songs_dir: str | Path):
        self.songs_dir = Path(songs_dir)

    # ---------------- git 呼び出し（このクラスの中だけ） ----------------
    def _run(self, args: list[str], cwd: Path | None = None, check: bool = True) -> str:
        exe = shutil.which("git")
        if not exe:
            raise HistoryUnavailable()
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        cwd = cwd or (self.songs_dir if self.songs_dir.is_dir() else self.songs_dir.parent)
        try:
            p = subprocess.run([exe, "-c", "core.quotepath=off", *args], cwd=cwd, env=env, capture_output=True,
                               timeout=_TIMEOUT, encoding="utf-8", errors="replace")
        except (OSError, subprocess.SubprocessError):
            raise HistoryUnavailable() from None
        if check and p.returncode != 0:
            raise HistoryError("履歴の操作に失敗しました")
        return p.stdout if p.returncode == 0 else ""

    def _top(self) -> Path:
        if not self.songs_dir.is_dir():
            raise HistoryUnavailable()
        out = self._run(["rev-parse", "--show-toplevel"], check=False).strip()
        if not out:
            raise HistoryUnavailable()
        return Path(out)

    def _rel(self, name: str) -> tuple[Path, str]:
        if not name or re.search(r"[\\/]", name) or name.startswith("."):
            raise HistoryError(f"曲の名前が正しくありません: {name}")
        top = self._top()
        path = (self.songs_dir / f"{name}.yaml").resolve()
        try:
            rel = path.relative_to(top.resolve())
        except ValueError:
            raise HistoryUnavailable() from None
        return top, rel.as_posix()

    # ---------------- 公開 API ----------------
    def available(self) -> bool:
        try:
            self._top()
            return True
        except HistoryError:
            return False

    def status(self) -> dict:
        ok = self.available()
        return {"available": ok, "message": "" if ok else UNAVAILABLE_MESSAGE}

    def save_version(self, name: str, note: str = "") -> dict:
        """曲の今のファイルを履歴に載せる。前のバージョンと同じ内容なら載せない。"""
        note = (note or "").strip()
        top, rel = self._rel(name)
        with _lock:
            if not (top / rel).is_file():
                raise HistoryError(f"曲が見つかりません: {name}（先に保存してください）")
            commits = self._commits(top, rel)
            if commits:
                last = self._show(top, commits[0][0], rel)
                if last == (top / rel).read_text(encoding="utf-8"):
                    return {"saved": False, "message": "前のバージョンから変更がありません", "no": len(commits)}
            self._run(["add", "--", rel], cwd=top)
            msg = f"{note or _DEFAULT_NOTE}\n\n{KIND_VERSION}: 1\n{SONG_TRAILER}: {rel}"
            ident = []
            if not self._run(["config", "user.name"], cwd=top, check=False).strip():
                ident += ["-c", "user.name=music-Ai"]
            if not self._run(["config", "user.email"], cwd=top, check=False).strip():
                ident += ["-c", "user.email=music-ai@localhost"]
            self._run([*ident, "commit", "--only", "--allow-empty", "--no-verify", "--no-gpg-sign", "-q", "-m", msg, "--", rel], cwd=top)
        return {"saved": True, "message": "バージョンを保存しました", "no": len(commits) + 1}

    def list_versions(self, name: str) -> list[Version]:
        """古い順。no は 1 から。"""
        top, rel = self._rel(name)
        commits = list(reversed(self._commits(top, rel)))  # 古い順
        out: list[Version] = []
        prev_text = None
        for i, (h, at, body) in enumerate(commits, 1):
            text = self._show(top, h, rel)
            summary = "最初のバージョン" if prev_text is None else summarize_change(prev_text, text)
            out.append(Version(i, at, _note_of(body), summary))
            prev_text = text
        return out

    def lyrics_diff(self, name: str, no_a: int, no_b: int) -> dict:
        """版 no_a → no_b の歌詞の差分（行単位。追加・削除・変更）。"""
        top, rel = self._rel(name)
        commits = list(reversed(self._commits(top, rel)))
        for no in (no_a, no_b):
            if not 1 <= no <= len(commits):
                raise HistoryError(f"バージョン {no} がありません")
        ta = self._show(top, commits[no_a - 1][0], rel)
        tb = self._show(top, commits[no_b - 1][0], rel)
        info = lambda n: {"no": n, "at": commits[n - 1][1], "note": _note_of(commits[n - 1][2])}  # noqa: E731
        return {"a": info(no_a), "b": info(no_b), "sections": diff_lyrics(ta, tb)}

    # ---------------- 内部 ----------------
    def _commits(self, top: Path, rel: str) -> list[tuple[str, str, str]]:
        """新しい順の [(内部 ID, 日時, メッセージ本文)]。この曲の印のあるものだけ。"""
        out = self._run(["log", f"--grep=^{KIND_VERSION}: 1$", "--format=%H%x1f%aI%x1f%B%x1e"], cwd=top, check=False)
        rows = []
        for rec in out.split("\x1e"):
            rec = rec.strip("\n")
            if not rec.strip():
                continue
            h, at, body = rec.split("\x1f", 2)
            if f"{SONG_TRAILER}: {rel}" in body.splitlines():
                rows.append((h.strip(), at, body))
        return rows

    def _show(self, top: Path, h: str, rel: str) -> str:
        return self._run(["show", f"{h}:{rel}"], cwd=top, check=False)


def _note_of(body: str) -> str:
    lines = [ln for ln in body.strip().splitlines() if not ln.startswith(("Musicai-Version:", f"{SONG_TRAILER}:"))]
    note = "\n".join(lines).strip()
    return "" if note == _DEFAULT_NOTE else note


# ---------------- 差分（git を使わない純粋関数） ----------------
def _load(text: str) -> dict:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def phrase_lines(lyrics) -> list[str]:
    """歌詞を 1 行 = 1 フレーズに分ける（改行か / で区切る）。"""
    if not isinstance(lyrics, str):
        return []
    return [p.strip() for p in re.split(r"[\n/／]", lyrics) if p.strip()]


def diff_lyrics(text_a: str, text_b: str) -> list[dict]:
    """セクションごとの行差分。type は same / add / remove / change。"""
    a, b = _load(text_a), _load(text_b)
    sa, sb = a.get("sections") or {}, b.get("sections") or {}
    names = list(dict.fromkeys([*sb, *sa]))
    result = []
    for n in names:
        la = phrase_lines((sa.get(n) or {}).get("lyrics") if isinstance(sa.get(n), dict) else None)
        lb = phrase_lines((sb.get(n) or {}).get("lyrics") if isinstance(sb.get(n), dict) else None)
        if not la and not lb:
            continue
        lines = []
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=la, b=lb, autojunk=False).get_opcodes():
            if op == "equal":
                lines += [{"type": "same", "text": t} for t in lb[j1:j2]]
            elif op == "insert":
                lines += [{"type": "add", "text": t} for t in lb[j1:j2]]
            elif op == "delete":
                lines += [{"type": "remove", "text": t} for t in la[i1:i2]]
            else:  # replace: 行数が合う分は「変更」、余りは追加・削除
                old, new = la[i1:i2], lb[j1:j2]
                for k in range(max(len(old), len(new))):
                    if k < len(old) and k < len(new):
                        lines.append({"type": "change", "old": old[k], "new": new[k]})
                    elif k < len(new):
                        lines.append({"type": "add", "text": new[k]})
                    else:
                        lines.append({"type": "remove", "text": old[k]})
        status = "removed" if n not in sb else ("added" if n not in sa else "kept")
        result.append({"name": n, "status": status, "changed": any(x["type"] != "same" for x in lines),
                       "lines": lines})
    return result


_META = [("title", "タイトル"), ("key", "キー"), ("tempo", "テンポ"), ("time", "拍子"), ("style", "アレンジ"),
         ("structure", "構成")]
_PARTS = [("lyrics", "歌詞"), ("melody", "メロディ"), ("chords", "コード")]


def summarize_change(old_text: str, new_text: str) -> str:
    """前のバージョンからの変更概要（例: 「歌詞 A・B／メロディ サビ／テンポ」）。"""
    a, b = _load(old_text), _load(new_text)
    parts = []
    sa, sb = a.get("sections") or {}, b.get("sections") or {}
    for key, label in _PARTS:
        names = [n for n in sb if n in sa and _field(sa, n, key) != _field(sb, n, key)]
        if names:
            parts.append(f"{label} " + "・".join(names))
    added = [n for n in sb if n not in sa]
    removed = [n for n in sa if n not in sb]
    if added:
        parts.append("追加 " + "・".join(added))
    if removed:
        parts.append("削除 " + "・".join(removed))
    other = [n for n in sb if n in sa and _field(sa, n, "") != _field(sb, n, "")
             and all(_field(sa, n, k) == _field(sb, n, k) for k, _ in _PARTS)]
    if other:
        parts.append("設定 " + "・".join(other))
    parts += [label for key, label in _META if a.get(key) != b.get(key)]
    return "／".join(parts) if parts else "変更なし（細かい書き方の違いのみ）"


def _field(sections: dict, name: str, key: str):
    sec = sections.get(name)
    if not isinstance(sec, dict):
        return None
    return sec.get(key) if key else sec
