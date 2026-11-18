import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from musicai import service, tools
from musicai.tools import ToolError

ROOT = Path(__file__).resolve().parent.parent
SPEC = {"title": "ツール試験", "key": "C major", "tempo": 100, "seed": 1, "structure": ["v"],
        "sections": {"v": {"progression": "I V vi IV", "lyrics": "あいうえおかきくけこ / さしすせそ"}}}
# 歌う音符 2 つに歌詞 3 モーラ → check の警告が出る曲
MISMATCH = "schema_version: 1\nkey: C major\ntempo: 100\nsections:\n  A:\n    chords: C\n    melody: C4:2 D4:2\n    lyrics: あいう\n"
TINY = "schema_version: 1\nkey: C major\ntempo: 120\nsections:\n  A:\n    chords: C\n    melody: C4:2 D4:2\n    lyrics: あい\n"


class ToolsCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        base = Path(self._td.name)
        self.base = base
        for d in ("songs", "specs", "output"):
            (base / d).mkdir()
        self._p = mock.patch.multiple(service, DATA_DIR=base, SONGS_DIR=base / "songs", SPECS_DIR=base / "specs",
                                      OUTPUT_DIR=base / "output")
        self._p.start()
        shutil.copy(ROOT / "songs" / "hoshi.yaml", base / "songs" / "hoshi.yaml")

    def tearDown(self):
        self._p.stop()
        self._td.cleanup()

    def put(self, name, text, d="songs"):
        (self.base / d / f"{name}.yaml").write_text(text, encoding="utf-8")


class ComposeTest(ToolsCase):
    def test_inline_spec_saves_valid_song(self):
        r = tools.call("compose", {"spec": SPEC})  # schema_version が無くても補う
        self.assertEqual((r["name"], r["path"]), ("ツール試験", "songs/ツール試験.yaml"))
        self.assertEqual(r["warnings"], [])
        self.assertTrue(tools.call("validate", {"name": "ツール試験", "check": True})["ok"])

    def test_overwrite_protection(self):
        tools.call("compose", {"spec": SPEC, "name": "x"})
        with self.assertRaises(ToolError) as cm:
            tools.call("compose", {"spec": SPEC, "name": "x"})
        self.assertIn("overwrite", str(cm.exception))
        self.assertEqual(tools.call("compose", {"spec": SPEC, "name": "x", "overwrite": True})["name"], "x")

    def test_bad_spec_reports_key_path(self):
        bad = {**SPEC, "sections": {"v": {"progresion": "I"}}}
        with self.assertRaises(ToolError) as cm:
            tools.call("compose", {"spec": bad})
        self.assertIn("sections.v.progresion", str(cm.exception))

    def test_spec_file_must_be_mapping(self):
        self.put("lst", "- 1\n- 2\n", "specs")
        with self.assertRaises(ToolError) as cm:
            tools.call("compose", {"spec_name": "lst"})
        self.assertIn("マップ", str(cm.exception))

    def test_spec_arguments(self):
        for args in ({}, {"spec": SPEC, "spec_name": "a"}):
            with self.assertRaises(ToolError):
                tools.call("compose", args)
        with self.assertRaises(ToolError):
            tools.call("compose", {"spec_name": "none"})
        self.put("h", yaml.safe_dump({"schema_version": 1, **SPEC}, allow_unicode=True), "specs")
        self.assertEqual(tools.call("compose", {"spec_name": "h", "name": "fromfile"})["name"], "fromfile")


class KaeutaTest(ToolsCase):
    def test_kaeuta_saves_new_song(self):
        r = tools.call("kaeuta", {"song": "hoshi", "lyrics": {"A": "ラーメンたべたい / チャーシューおおめで"}, "title": "替"})
        self.assertEqual(r["name"], "hoshi_kaeuta")
        self.assertTrue(r["report"])
        self.assertTrue(tools.call("validate", {"name": "hoshi_kaeuta"})["ok"])
        with self.assertRaises(ToolError):  # 同名は上書きしない
            tools.call("kaeuta", {"song": "hoshi", "lyrics": {"A": "あいうえお"}})

    def test_errors(self):
        with self.assertRaises(ToolError):
            tools.call("kaeuta", {"song": "none", "lyrics": {"A": "あ"}})
        with self.assertRaises(ToolError) as cm:
            tools.call("kaeuta", {"song": "hoshi", "lyrics": {"ZZ": "あ"}})
        self.assertIn("ZZ", str(cm.exception))
        with self.assertRaises(ToolError):
            tools.call("kaeuta", {"song": "hoshi", "lyrics": {}})


class ValidateTest(ToolsCase):
    def test_name_and_yaml(self):
        self.assertEqual(tools.call("validate", {"name": "hoshi"}), {"ok": True, "kind": "song", "errors": []})
        r = tools.call("validate", {"yaml": "title: x\n"})
        self.assertFalse(r["ok"])
        self.assertEqual({e["path"] for e in r["errors"]}, {"schema_version", "sections"})
        self.assertEqual(tools.call("validate", {"yaml": ": [\n"})["errors"][0]["path"], "(yaml)")
        self.put("sp", yaml.safe_dump({"schema_version": 1, **SPEC}, allow_unicode=True), "specs")
        self.assertTrue(tools.call("validate", {"name": "sp", "kind": "spec"})["ok"])

    def test_check_returns_warnings(self):
        self.put("m", MISMATCH)
        r = tools.call("validate", {"name": "m", "check": True})
        self.assertTrue(r["ok"])
        self.assertTrue(r["warnings"])
        r = tools.call("validate", {"yaml": "schema_version: 1\nsections:\n  A:\n    chords: ZZZ\n", "check": True})
        self.assertFalse(r["ok"])  # コード名が読めない → 楽曲として読めない
        self.assertEqual(r["errors"][-1]["path"], "(song)")

    def test_arguments(self):
        for args in ({}, {"name": "a", "yaml": "x"}):
            with self.assertRaises(ToolError):
                tools.call("validate", args)
        with self.assertRaises(ToolError):
            tools.call("validate", {"name": "none"})


class ExportTest(ToolsCase):
    def test_default_formats(self):
        r = tools.call("export", {"name": "hoshi"})
        self.assertEqual(set(r["files"]), {"midi", "musicxml", "lyrics"})
        for rel in r["files"].values():
            self.assertTrue((self.base / rel).is_file(), rel)
        self.assertFalse((self.base / "output" / "hoshi.wav").exists())  # 音は作らない

    def test_gate_blocks_warnings_and_invalid(self):
        self.put("m", MISMATCH)
        with self.assertRaises(ToolError) as cm:
            tools.call("export", {"name": "m"})
        self.assertIn("警告", str(cm.exception))
        self.assertFalse((self.base / "output" / "m.mid").exists())
        r = tools.call("export", {"name": "m", "allow_warnings": True})
        self.assertTrue(r["warnings"])
        self.put("bad", "title: x\nsections:\n  A:\n    chords: C\n")
        with self.assertRaises(ToolError) as cm:
            tools.call("export", {"name": "bad"})
        self.assertIn("schema_version", str(cm.exception))

    def test_song_that_cannot_be_read_and_missing_formats(self):
        self.put("z", "schema_version: 1\nsections:\n  A:\n    chords: ZZZ\n")  # 構造は正しいが楽曲として読めない
        with self.assertRaises(ToolError):
            tools.call("export", {"name": "z"})
        real = service.render_song
        with mock.patch.object(service, "render_song", side_effect=lambda *a, **k: {
                k2: v for k2, v in real(*a, **k).items() if k2 != "mp3"}):
            self.put("t", TINY)
            r = tools.call("export", {"name": "t", "formats": ["wav", "mp3"]})
        self.assertEqual(r["missing"], ["mp3"])
        self.assertIn("ffmpeg", r["note"])

    def test_wav(self):
        self.put("t", TINY)
        r = tools.call("export", {"name": "t", "formats": ["wav", "midi", "midi"]})
        self.assertEqual(list(r["files"]), ["wav", "midi"])
        self.assertTrue((self.base / r["files"]["wav"]).is_file())

    def test_unknown_song_and_no_path_escape(self):
        for name in ("none", "../../etc/passwd", "../songs/hoshi"):
            with self.assertRaises(ToolError):
                tools.call("export", {"name": name})

    def test_cli_export(self):
        import contextlib, io
        from musicai.__main__ import main
        out = self.base / "o2"
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            main(["export", str(self.base / "songs" / "hoshi.yaml"), "-o", str(out), "--format", "midi,lyrics"])
        self.assertTrue((out / "hoshi.mid").is_file())
        self.assertIn("lyrics", buf.getvalue())
        with self.assertRaises(SystemExit):
            main(["export", str(self.base / "songs" / "hoshi.yaml"), "--format", "ogg"])
        self.put("m", MISMATCH)
        with self.assertRaises(SystemExit):
            main(["export", str(self.base / "songs" / "m.yaml"), "-o", str(out)])


class CallTest(ToolsCase):
    def test_input_validation(self):
        with self.assertRaises(ToolError) as cm:
            tools.call("nope", {})
        self.assertIn("compose", str(cm.exception))
        for name, args in (("export", {}), ("export", {"name": 1}), ("export", {"name": "a", "extra": 1}),
                           ("export", {"name": "a", "formats": ["ogg"]}), ("kaeuta", {"song": "a", "lyrics": {"A": 1}}),
                           ("validate", {"kind": "other", "name": "a"})):
            with self.assertRaises(ToolError, msg=(name, args)):
                tools.call(name, args)
        with self.assertRaises(ToolError):
            tools.call("export", None)  # None は {} 扱い → name が足りない


if __name__ == "__main__":
    unittest.main()
