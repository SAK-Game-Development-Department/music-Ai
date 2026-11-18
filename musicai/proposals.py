"""AI の修正案（提案）の保管と、採用・却下。

原則: AI の変更は「提案」として別に保持し、人が採用したときだけ曲に反映して履歴（バージョン）に載せる。

- 提案は proposals/<曲名>/<番号>.json に保存する（Git の外）。Git が無い環境でも使える。
- 提出時の「元の曲の内容」も一緒に保存する。あとで曲が変わっていないか（stale）の判定と、
  衝突の解決（merge.py）に使う。
- 採用すると、曲のファイルを提案の内容にして、「提案を採用: <タイトル>」のバージョンを保存する。
  今の曲がまだバージョンになっていなければ、先に自動で残す（採用も取り消せる）。
- 提案のあとに曲が変わっていた場合（stale）は、そのままでは採用できない（ProposalConflict）。
  解決は merge.py（C4）が担当する（衝突したセクションごとに、自分の版か提案かを選ぶ）。
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path

import yaml

from .history import History, HistoryError, HistoryUnavailable, diff_lyrics, summarize_change
from .migrate import migrate_text
from .schema import validate_data

MAX_YAML_BYTES = 1_000_000
MAX_TITLE = 80
MAX_REASON = 2000
STATUS_LABEL = {"pending": "検討中", "adopted": "採用", "rejected": "却下"}
_lock = threading.Lock()


class ProposalError(ValueError):
    """利用者に見せてよい、日本語のエラー。"""


class ProposalConflict(ProposalError):
    """提案を出したあとに、曲が変更されている。"""


class Proposals:
    def __init__(self, root: str | Path, songs_dir: str | Path):
        self.root = Path(root)
        self.songs_dir = Path(songs_dir)

    # ---------------- パス ----------------
    def _song_name(self, song: str) -> str:
        from .service import safe_name

        return safe_name(song)

    def _song_file(self, name: str) -> Path:
        return self.songs_dir / f"{name}.yaml"

    def _dir(self, name: str) -> Path:
        return self.root / name

    def _read(self, name: str, pid: int) -> dict:
        p = self._dir(name) / f"{int(pid):04d}.json"
        if not p.is_file():
            raise ProposalError(f"提案 {pid} が見つかりません")
        return json.loads(p.read_text(encoding="utf-8"))

    def _write(self, name: str, rec: dict) -> None:
        d = self._dir(name)
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{rec['id']:04d}.json"
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)  # 途中で止まっても、壊れたファイルを残さない

    def _all(self, name: str) -> list[dict]:
        d = self._dir(name)
        if not d.is_dir():
            return []
        out = []
        for p in sorted(d.glob("*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue  # 壊れたファイルは一覧から外す（ほかの提案は使える）
        return out

    def _current(self, name: str) -> str | None:
        f = self._song_file(name)
        return f.read_text(encoding="utf-8") if f.is_file() else None

    # ---------------- 提出 ----------------
    def submit(self, song: str, yaml_text: str, title: str, reason: str = "") -> dict:
        name = self._song_name(song)
        title, reason = (title or "").strip(), (reason or "").strip()
        if not title:
            raise ProposalError("提案のタイトルを入れてください")
        if len(title) > MAX_TITLE or len(reason) > MAX_REASON:
            raise ProposalError(f"タイトルは {MAX_TITLE} 文字、理由は {MAX_REASON} 文字までです")
        if len((yaml_text or "").encode("utf-8")) > MAX_YAML_BYTES:
            raise ProposalError("提案の YAML が大きすぎます")
        current = self._current(name)
        if current is None:
            raise ProposalError(f"曲が見つかりません: {name}（提案は、保存済みの曲に対して出します）")
        try:
            data = yaml.safe_load(yaml_text)
        except yaml.YAMLError:
            raise ProposalError("提案の YAML が読めません") from None
        if not isinstance(data, dict):
            raise ProposalError("提案の YAML は、曲のデータ（キーと値）で書いてください")
        try:
            text, _, _ = migrate_text(yaml_text)  # schema_version が無ければ補う（コメントは保つ）
        except ValueError as e:
            raise ProposalError(str(e)) from None
        r = validate_data(yaml.safe_load(text), "song")
        if not r.ok:
            raise ProposalError("提案の形式が正しくありません:\n" + r.format())
        from .song import song_from_dict

        try:
            song_obj = song_from_dict(yaml.safe_load(text))
        except ValueError as e:
            raise ProposalError(f"提案が曲として読めません: {e}") from None
        if text == current:
            raise ProposalError("今の曲と同じ内容です（変更がありません）")
        with _lock:
            ids = [x["id"] for x in self._all(name)]
            rec = {"id": max(ids, default=0) + 1, "title": title, "reason": reason, "status": "pending",
                   "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                   "yaml": text, "base": current,
                   "warnings": [w for s in song_obj.sections.values() for w in s.warnings],
                   "adopted_version": None}
            self._write(name, rec)
        return self._summary(rec, current)

    # ---------------- 一覧・詳細 ----------------
    def _summary(self, rec: dict, current: str | None) -> dict:
        cur = current if current is not None else ""
        return {"id": rec["id"], "title": rec["title"], "reason": rec["reason"], "status": rec["status"],
                "status_label": STATUS_LABEL.get(rec["status"], rec["status"]), "at": rec["created_at"],
                "summary": summarize_change(cur, rec["yaml"]), "warnings": rec.get("warnings", []),
                "stale": rec["status"] == "pending" and current is not None and rec.get("base") != current,
                "adopted_version": rec.get("adopted_version")}

    def list(self, song: str) -> list[dict]:
        """検討中を先に、新しい順。"""
        name = self._song_name(song)
        cur = self._current(name)
        items = [self._summary(r, cur) for r in self._all(name)]
        return sorted(items, key=lambda x: (x["status"] != "pending", -x["id"]))

    def get(self, song: str, pid: int) -> dict:
        """詳細（歌詞の差分つき。差分は「今の曲 → 提案」）。"""
        name = self._song_name(song)
        rec = self._read(name, pid)
        cur = self._current(name)
        out = self._summary(rec, cur)
        out["lyrics"] = diff_lyrics(cur or "", rec["yaml"])
        return out

    def yaml_of(self, song: str, pid: int) -> str:
        return self._read(self._song_name(song), pid)["yaml"]

    # ---------------- 採用・却下 ----------------
    def conflicts(self, song: str, pid: int) -> dict:
        """提案を出したあとに曲が変わっているとき、何が自動で取り込まれ、何が衝突するか。"""
        from . import merge

        name = self._song_name(song)
        rec = self._read(name, pid)
        if rec["status"] != "pending":
            raise ProposalError(f"この提案は、すでに「{STATUS_LABEL.get(rec['status'])}」です")
        cur = self._current(name)
        if cur is None:
            raise ProposalError(f"曲が見つかりません: {name}")
        out = merge.analyze(rec.get("base") or "", cur, rec["yaml"])
        out["stale"] = rec.get("base") != cur
        return out

    def adopt(self, song: str, pid: int, history: History | None = None, choices: dict | None = None) -> dict:
        """採用する。曲が変わっていた（stale）ときは、choices（単位の id → mine / theirs）で衝突を解決する。"""
        from . import merge

        name = self._song_name(song)
        with _lock:
            rec = self._read(name, pid)
            if rec["status"] != "pending":
                raise ProposalError(f"この提案は、すでに「{STATUS_LABEL.get(rec['status'])}」です")
            current = self._current(name)
            if current is None:
                raise ProposalError(f"曲が見つかりません: {name}")
            text, resolved = rec["yaml"], False
            if rec.get("base") != current:
                if choices is None:
                    raise ProposalConflict("この提案を出したあとに、曲が変更されています。変更が重なるところを選んで解決してください")
                plan = merge.analyze(rec.get("base") or "", current, rec["yaml"])
                undecided = [u["label"] for u in plan["units"] if u["decision"] == "conflict" and u["id"] not in choices]
                if undecided:
                    raise ProposalConflict("まだ選んでいない衝突があります: " + "、".join(undecided))
                text, resolved = merge.resolve(rec.get("base") or "", current, rec["yaml"], choices), True
                if text == current:
                    raise ProposalError("選んだ結果が、今の曲と同じ内容です（変わるところがありません）。不要な提案なら「却下」してください")
            auto = None
            if history is not None:  # 採用も取り消せるよう、今の内容を先にバージョンとして残す
                try:
                    r = history.save_version(name, "提案の採用前の自動保存")
                    auto = r["no"] if r["saved"] else None
                except HistoryUnavailable:
                    history = None
            self._song_file(name).write_text(text, encoding="utf-8")
            no = None
            if history is not None:
                try:
                    note = f"提案を採用（衝突を解決）: {rec['title']}" if resolved else f"提案を採用: {rec['title']}"
                    no = history.save_version(name, note)["no"]
                except HistoryError:
                    no = None
            rec.update(status="adopted", adopted_version=no, resolved=resolved,
                       decided_at=datetime.now().astimezone().isoformat(timespec="seconds"))
            self._write(name, rec)
        msg = "提案を採用しました" + ("（バージョンに保存しました）" if no else "（履歴機能は使えないため、バージョンは保存していません）")
        return {"adopted": True, "message": msg, "version": no, "auto_saved": auto}

    def reject(self, song: str, pid: int) -> dict:
        name = self._song_name(song)
        with _lock:
            rec = self._read(name, pid)
            if rec["status"] != "pending":
                raise ProposalError(f"この提案は、すでに「{STATUS_LABEL.get(rec['status'])}」です")
            rec.update(status="rejected", decided_at=datetime.now().astimezone().isoformat(timespec="seconds"))
            self._write(name, rec)
        return {"rejected": True, "message": "提案を却下しました"}
