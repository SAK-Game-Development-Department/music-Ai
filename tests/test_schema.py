import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml

from musicai import schema
from musicai.__main__ import main
from musicai.composer import compose
from musicai.schema import (SchemaError, detect_kind, validate_against, validate_data, validate_file)

ROOT = Path(__file__).resolve().parent.parent
GOOD_SONG = {"schema_version": 1, "title": "t", "key": "C major", "tempo": 100, "time": "4/4", "style": "pop",
             "structure": ["A"], "sections": {"A": {"chords": "C | F", "melody": "C4:1", "lyrics": "あ",
                                                    "energy": "mid", "bars": 2, "fit": True}}}


def paths(r):
    return [p for p, _ in r.errors]


class ShippedFilesTest(unittest.TestCase):
    def test_all_songs_and_specs_validate(self):
        files = [(f, "song") for f in sorted((ROOT / "songs").glob("*.yaml"))]
        files += [(f, "spec") for f in sorted((ROOT / "specs").glob("*.yaml"))]
        self.assertTrue(files)
        for f, kind in files:
            r = validate_file(f)
            self.assertTrue(r.ok, f"{f}: {r.errors}")
            self.assertEqual(detect_kind(f, yaml.safe_load(f.read_text(encoding="utf-8"))), kind)

    def test_compose_output_validates(self):
        spec = yaml.safe_load((ROOT / "specs" / "hajimari.yaml").read_text(encoding="utf-8"))
        r = validate_data(compose(spec), "song")
        self.assertTrue(r.ok, r.errors)

    def test_cli_validate_and_check_gate(self):
        with tempfile.TemporaryDirectory() as d:
            old = Path(d) / "old.yaml"
            old.write_text("# c\ntitle: x\nsections:\n  A:\n    chords: C\n", encoding="utf-8")
            with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
                main(["validate", str(old)])
            with self.assertRaises(SystemExit) as cm:
                main(["check", str(old)])
            self.assertIn("migrate", str(cm.exception))
            with redirect_stdout(io.StringIO()):
                main(["migrate", str(old)])
                main(["validate", str(old)])
                main(["check", str(old)])


class ValidationTest(unittest.TestCase):
    def bad(self, mutate, kind="song"):
        d = copy.deepcopy(GOOD_SONG)
        mutate(d)
        return validate_data(d, kind)

    def test_good(self):
        r = validate_data(GOOD_SONG)
        self.assertTrue(r.ok)
        self.assertEqual(r.errors, [])

    def test_required_and_unknown_key(self):
        r = self.bad(lambda d: d.pop("schema_version"))
        self.assertEqual(paths(r), ["schema_version"])
        r = self.bad(lambda d: d.update(sectoins={}))
        self.assertEqual(paths(r), ["sectoins"])
        r = self.bad(lambda d: d["sections"]["A"].update(melodyy="x"))
        self.assertEqual(paths(r), ["sections.A.melodyy"])

    def test_types_and_error_path(self):
        r = self.bad(lambda d: d["sections"]["A"].update(melody=5))
        self.assertEqual(paths(r), ["sections.A.melody"])
        r = self.bad(lambda d: d.update(structure=["A", 3]))
        self.assertEqual(paths(r), ["structure[1]"])
        r = self.bad(lambda d: d.update(schema_version=True))  # bool は整数ではない
        self.assertEqual(paths(r), ["schema_version"])
        r = self.bad(lambda d: d["sections"]["A"].update(fit="yes"))
        self.assertEqual(paths(r), ["sections.A.fit"])
        self.assertEqual(paths(validate_data([1])), ["(root)"])

    def test_enum_pattern_numbers(self):
        self.assertEqual(paths(self.bad(lambda d: d.update(style="jazz"))), ["style"])
        self.assertEqual(paths(self.bad(lambda d: d.update(time="four"))), ["time"])
        self.assertEqual(paths(self.bad(lambda d: d.update(tempo=0))), ["tempo"])
        self.assertEqual(paths(self.bad(lambda d: d.update(schema_version=0))), ["schema_version"])
        self.assertEqual(paths(self.bad(lambda d: d["sections"]["A"].update(bars=0))), ["sections.A.bars"])
        self.assertTrue(self.bad(lambda d: d.update(tempo=96.5)).ok)

    def test_sections(self):
        self.assertEqual(paths(self.bad(lambda d: d.update(sections={}))), ["sections"])
        self.assertTrue(self.bad(lambda d: d["sections"].update(B=None)).ok)  # 空のセクション
        self.assertEqual(paths(self.bad(lambda d: d["sections"].update(B="x"))), ["sections.B"])

    def test_spec_kind(self):
        spec = {"schema_version": 1, "seed": 3, "sections": {"v": {"progression": "I V", "register": "high",
                                                                    "transpose_range": -5}}}
        self.assertTrue(validate_data(spec, "spec").ok)
        self.assertEqual(paths(validate_data(spec, "song")), ["seed", "sections.v.progression",
                                                              "sections.v.register", "sections.v.transpose_range"])
        with self.assertRaises(ValueError):
            validate_data(spec, "other")

    def test_detect_kind_by_content(self):
        self.assertEqual(detect_kind("x/a.yaml", {"seed": 1, "sections": {}}), "spec")
        self.assertEqual(detect_kind("x/a.yaml", {"sections": {"v": {"progression": "I"}}}), "spec")
        self.assertEqual(detect_kind("x/a.yaml", {"sections": {"A": {"chords": "C"}}}), "song")
        self.assertEqual(detect_kind("x/a.yaml", [1]), "song")
        self.assertEqual(detect_kind("x/a.yaml"), "song")

    def test_file_errors(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(paths(validate_file(Path(d) / "none.yaml")), ["(file)"])
            p = Path(d) / "bad.yaml"
            p.write_text("a: [1,\n", encoding="utf-8")
            self.assertEqual(paths(validate_file(p)), ["(yaml)"])
            p.write_text("", encoding="utf-8")
            self.assertEqual(paths(validate_file(p)), ["(root)"])


class KeywordCoverageTest(unittest.TestCase):
    """同梱スキーマで使わないキーワードも含め、対応する全キーワードを直接試す。"""

    def test_each_keyword(self):
        cases = [
            ({"type": "number"}, 1.5, 1, "x"),
            ({"type": ["integer", "null"]}, None, 2, "s"),
            ({"type": "boolean"}, False, True, 0),
            ({"type": "array", "items": {"type": "string"}}, ["a"], [], [1]),
            ({"enum": ["a", "b"]}, "a", "b", "c"),
            ({"const": 1}, 1, 1, 2),
            ({"pattern": "^a"}, "ab", "a", "ba"),
            ({"minimum": 2}, 2, 3, 1),
            ({"exclusiveMinimum": 2}, 3, 2.5, 2),
            ({"type": "object", "minProperties": 1}, {"a": 1}, {"b": 1}, {}),
            ({"type": "object", "required": ["a"]}, {"a": 1}, {"a": 2, "b": 3}, {"b": 3}),
            ({"type": "object", "additionalProperties": {"type": "integer"}}, {"x": 1}, {}, {"x": "s"}),
            ({"type": "object", "properties": {"a": {"type": "integer"}}}, {"a": 1}, {"z": 1}, {"a": "s"}),
        ]
        for sch, ok1, ok2, ng in cases:
            self.assertTrue(validate_against(ok1, sch).ok, (sch, ok1))
            self.assertTrue(validate_against(ok2, sch).ok, (sch, ok2))
            self.assertFalse(validate_against(ng, sch).ok, (sch, ng))

    def test_ref_and_errors(self):
        sch = {"$defs": {"n": {"type": "integer"}}, "type": "object", "properties": {"a": {"$ref": "#/$defs/n"}}}
        self.assertTrue(validate_against({"a": 1}, sch).ok)
        self.assertEqual(paths(validate_against({"a": "x"}, sch)), ["a"])
        with self.assertRaises(SchemaError):
            validate_against(1, {"oneOf": []})
        with self.assertRaises(SchemaError):
            validate_against(1, {"$ref": "http://x"})
        with self.assertRaises(SchemaError):
            validate_against(1, {"type": "date"})

    def test_shipped_schemas_use_only_supported_keywords(self):
        def keys(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    yield k
                    if k in ("properties", "$defs"):
                        for sub in v.values():
                            yield from keys(sub)
                    elif k in ("additionalProperties", "items") and isinstance(v, dict):
                        yield from keys(v)
                    elif k not in ("enum", "required", "type", "const"):
                        pass
        for kind in schema.KINDS:
            self.assertFalse(set(keys(schema.load_schema(kind))) - schema.SUPPORTED, kind)


class JsonschemaParityTest(unittest.TestCase):
    """jsonschema が入っている環境では、自前検証と合否が一致することを確認する。"""

    def test_parity(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema 未インストール")
        samples = [GOOD_SONG]
        for mut in [lambda d: d.pop("schema_version"), lambda d: d.update(style="x"), lambda d: d.update(tempo=0),
                    lambda d: d["sections"]["A"].update(bars=0), lambda d: d.update(extra=1),
                    lambda d: d.update(time="x"), lambda d: d.update(sections={})]:
            d = copy.deepcopy(GOOD_SONG)
            mut(d)
            samples.append(d)
        for kind in ("song",):
            sch = schema.load_schema(kind)
            v = jsonschema.Draft202012Validator(sch)
            for d in samples:
                self.assertEqual(validate_data(d, kind).ok, v.is_valid(d), d)
        for f in (ROOT / "specs").glob("*.yaml"):
            d = yaml.safe_load(f.read_text(encoding="utf-8"))
            self.assertEqual(validate_data(d, "spec").ok, jsonschema.Draft202012Validator(
                schema.load_schema("spec")).is_valid(d))
        json.dumps(sch)


if __name__ == "__main__":
    unittest.main()
