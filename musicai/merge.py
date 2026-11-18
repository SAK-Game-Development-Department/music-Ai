"""3 点比較（提出時の元の内容 / 今の曲 / 提案）で、衝突があるセクションだけを選択式で解決する。

単位:
  - セクション（A・サビなど）… まるごと 1 単位
  - 曲全体の設定（テンポ・キー・アレンジ・構成など。sections 以外の最上位キー）… キーごとに 1 単位

各単位について、元の内容を b、今の曲を o（自分）、提案を t とする:
  o == t   … 同じ。何もしない
  o == b   … 提案だけが変えた。提案を取り込む（自動）
  t == b   … 自分だけが変えた。自分の内容を残す（自動）
  どれも違う … 衝突。人が「自分の版」か「提案」を選ぶ

注意: 合成した結果は YAML を作り直すので、ファイルの中のコメントは消える。
"""
from __future__ import annotations

from .history import _META, _load

_META_LABEL = dict(_META)
_MISSING = object()
CHOICES = ("mine", "theirs")


class MergeError(ValueError):
    """利用者に見せてよい、日本語のエラー。"""


def _show(v):
    return None if v is _MISSING else v


def _decide(b, o, t) -> str:
    if o == t:
        return "same"
    if o == b:
        return "theirs"  # 提案だけが変えた → 提案を取り込む
    if t == b:
        return "mine"    # 自分だけが変えた → 自分の内容を残す
    return "conflict"


def _units(base: str, cur: str, prop: str) -> list[dict]:
    B, O, T = _load(base), _load(cur), _load(prop)
    units: list[dict] = []
    keys = [k for k in dict.fromkeys([*O, *T, *B]) if k != "sections"]
    for k in keys:
        b, o, t = B.get(k, _MISSING), O.get(k, _MISSING), T.get(k, _MISSING)
        units.append({"id": f"meta:{k}", "kind": "meta", "key": k, "label": _META_LABEL.get(k, k),
                      "decision": _decide(b, o, t), "b": b, "o": o, "t": t})
    sb, so, st = (x.get("sections") if isinstance(x.get("sections"), dict) else {} for x in (B, O, T))
    for n in dict.fromkeys([*so, *st, *sb]):
        b, o, t = sb.get(n, _MISSING), so.get(n, _MISSING), st.get(n, _MISSING)
        units.append({"id": f"section:{n}", "kind": "section", "key": n, "label": n,
                      "decision": _decide(b, o, t), "b": b, "o": o, "t": t})
    return units


def _fields(u: dict) -> list[dict]:
    """セクションのどの項目が違うか（画面に見せる用）。"""
    b, o, t = u["b"], u["o"], u["t"]
    if u["kind"] == "meta":
        return [{"field": u["label"], "base": _show(b), "mine": _show(o), "theirs": _show(t)}]
    d = lambda x: x if isinstance(x, dict) else {}  # noqa: E731
    out = []
    for f in dict.fromkeys([*d(o), *d(t), *d(b)]):
        vb, vo, vt = d(b).get(f), d(o).get(f), d(t).get(f)
        if not (vb == vo == vt):
            out.append({"field": f, "base": vb, "mine": vo, "theirs": vt})
    if not out:  # セクションごとの追加・削除
        out.append({"field": "(セクション)", "base": "あり" if b is not _MISSING else "なし",
                    "mine": "あり" if o is not _MISSING else "なし", "theirs": "あり" if t is not _MISSING else "なし"})
    return out


def analyze(base: str, cur: str, prop: str) -> dict:
    """何が自動で取り込まれ、何が衝突しているか。"""
    rows = []
    for u in _units(base, cur, prop):
        if u["decision"] == "same":
            continue
        rows.append({"id": u["id"], "kind": u["kind"], "label": u["label"], "decision": u["decision"],
                     "fields": _fields(u)})
    return {"units": rows, "conflicts": [r["id"] for r in rows if r["decision"] == "conflict"]}


def resolve(base: str, cur: str, prop: str, choices: dict[str, str] | None) -> str:
    """選択を反映して合成した YAML テキストを返す。衝突が残っていればエラー。"""
    from .schema import validate_data
    from .service import dump_yaml
    from .song import song_from_dict

    choices = choices or {}
    for k, v in choices.items():
        if v not in CHOICES:
            raise MergeError(f"選択は {' か '.join(CHOICES)} のどちらかです: {k}={v!r}")
    units = _units(base, cur, prop)
    open_ = [u["label"] for u in units if u["decision"] == "conflict" and u["id"] not in choices]
    if open_:
        raise MergeError("まだ選んでいない衝突があります: " + "、".join(open_))
    merged: dict = {}
    sections: dict = {}
    for u in units:
        pick = {"same": "mine", "mine": "mine", "theirs": "theirs", "conflict": choices.get(u["id"])}[u["decision"]]
        v = u["o"] if pick == "mine" else u["t"]
        if v is _MISSING:
            continue  # その側ではなくなっている（削除）
        (merged if u["kind"] == "meta" else sections)[u["key"]] = v
    # schema_version などの最上位キーの順序は保ち、sections は最後に置く
    if sections:
        merged["sections"] = sections
    r = validate_data(merged, "song")
    if not r.ok:
        raise MergeError("合成した結果の形式が正しくありません:\n" + r.format())
    try:
        song_from_dict(merged)
    except ValueError as e:
        raise MergeError(f"合成した結果が曲として読めません（選び直してください）: {e}") from None
    return dump_yaml(merged)
