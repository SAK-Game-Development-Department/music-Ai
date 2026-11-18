"""ファイル構造の検証（schemas/*.schema.json）。楽曲ルールの検証は `check` の役割。

標準ライブラリだけの軽量検証器。対応する JSON Schema のキーワードは SUPPORTED のみ。
スキーマに未対応のキーワードを書くと SchemaError になる（黙って素通りさせない）。

    from musicai.schema import validate_file
    r = validate_file("songs/hoshi.yaml")
    r.ok, r.errors   # errors = [(キーのパス, 理由), ...]
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"
KINDS = ("song", "spec")
SUPPORTED = {
    "$schema", "$id", "$ref", "$defs", "title", "description",
    "type", "enum", "const", "properties", "required", "additionalProperties",
    "items", "minimum", "exclusiveMinimum", "pattern", "minProperties",
}


class SchemaError(Exception):
    """スキーマ自体の問題（対応外のキーワードなど）。"""


@dataclass
class ValidationResult:
    ok: bool
    errors: list[tuple[str, str]] = field(default_factory=list)

    def format(self) -> str:
        return "\n".join(f"  {p}: {m}" for p, m in self.errors)


def load_schema(kind: str) -> dict:
    if kind not in KINDS:
        raise ValueError(f"種類は {'/'.join(KINDS)} のどちらかです: {kind!r}")
    return json.loads((SCHEMA_DIR / f"{kind}.schema.json").read_text(encoding="utf-8"))


def _is_type(v, t: str) -> bool:
    if t == "object":
        return isinstance(v, dict)
    if t == "array":
        return isinstance(v, list)
    if t == "string":
        return isinstance(v, str)
    if t == "boolean":
        return isinstance(v, bool)
    if t == "null":
        return v is None
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    raise SchemaError(f"未対応の type: {t}")


_TYPE_JA = {"object": "マップ", "array": "リスト", "string": "文字列", "boolean": "true/false",
            "null": "空", "integer": "整数", "number": "数値"}


def _resolve(ref: str, root: dict) -> dict:
    if not ref.startswith("#/"):
        raise SchemaError(f"未対応の $ref: {ref}")
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _walk(value, schema: dict, root: dict, path: str, errors: list) -> None:
    unknown = set(schema) - SUPPORTED
    if unknown:
        raise SchemaError(f"未対応のキーワード: {sorted(unknown)}")
    if "$ref" in schema:
        _walk(value, _resolve(schema["$ref"], root), root, path, errors)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, t) for t in types):
            errors.append((path, f"{'か'.join(_TYPE_JA[t] for t in types)}で書いてください"))
            return
    if "enum" in schema and value not in schema["enum"]:
        errors.append((path, "次のいずれかにしてください: " + " / ".join(map(str, schema["enum"]))))
    if "const" in schema and value != schema["const"]:
        errors.append((path, f"{schema['const']!r} である必要があります"))
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        errors.append((path, f"書式が違います（{schema['pattern']}）"))
    if _is_type(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append((path, f"{schema['minimum']} 以上にしてください"))
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append((path, f"{schema['exclusiveMinimum']} より大きくしてください"))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append((f"{path}.{key}" if path else key, "必須です（ありません）"))
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            errors.append((path, f"{schema['minProperties']} 個以上の項目が必要です"))
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for k, v in value.items():
            sub = f"{path}.{k}" if path else str(k)
            if k in props:
                _walk(v, props[k], root, sub, errors)
            elif extra is False:
                errors.append((sub, "未知のキーです（綴りを確認してください）"))
            elif isinstance(extra, dict):
                _walk(v, extra, root, sub, errors)
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            _walk(v, schema["items"], root, f"{path}[{i}]", errors)


def validate_against(data, schema: dict) -> ValidationResult:
    """任意のスキーマ（dict）で検証する。"""
    errors: list[tuple[str, str]] = []
    _walk(data, schema, schema, "", errors)
    # ルート直下のエラーは "(root)" と表示する
    errors = [(p or "(root)", m) for p, m in errors]
    return ValidationResult(not errors, errors)


def validate_data(data, kind: str = "song") -> ValidationResult:
    return validate_against(data, load_schema(kind))


def detect_kind(path: str | Path, data=None) -> str:
    """specs/ 配下なら spec。それ以外は中身で判断（seed や progression があれば spec）。"""
    if Path(path).resolve().parent.name == "specs":
        return "spec"
    if isinstance(data, dict):
        secs = data.get("sections")
        has_prog = isinstance(secs, dict) and any(isinstance(s, dict) and "progression" in s for s in secs.values())
        if "seed" in data or has_prog:
            return "spec"
    return "song"


def validate_file(path: str | Path, kind: str | None = None) -> ValidationResult:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        return ValidationResult(False, [("(file)", f"読めません: {e.strerror or e}")])
    except yaml.YAMLError as e:
        return ValidationResult(False, [("(yaml)", f"YAML として読めません: {e}")])
    return validate_data(data, kind or detect_kind(path, data))
