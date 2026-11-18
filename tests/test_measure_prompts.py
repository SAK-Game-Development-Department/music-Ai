import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("measure_prompts", ROOT / "scripts" / "measure_prompts.py")
mp = importlib.util.module_from_spec(_spec)
sys.modules["measure_prompts"] = mp  # dataclass が自分のモジュールを引けるように
_spec.loader.exec_module(mp)

SPEC_OK = "schema_version: 1\nseed: 1\nsections:\n  v:\n    progression: I V\n    lyrics: あいう\n"
SPEC_BAD = "seed: 1\nsections:\n  v:\n    progresion: I V\n"
SONG_OK = "schema_version: 1\nsections:\n  A:\n    chords: C\n"


class MeasureTest(unittest.TestCase):
    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = mp.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_rate_with_yaml_and_markdown(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "a.yaml").write_text(SPEC_OK, encoding="utf-8")
            (d / "b.md").write_text(f"こちらです\n```yaml\n{SPEC_OK}```\n説明", encoding="utf-8")
            (d / "c.yaml").write_text(SPEC_BAD, encoding="utf-8")
            (d / "d.md").write_text("YAML なし", encoding="utf-8")
            (d / "e.txt").write_text("```yaml\na: [1,\n```", encoding="utf-8")
            (d / "ignored.json").write_text("{}", encoding="utf-8")
            items = mp.measure([str(d)], "spec")
            self.assertEqual([i.ok for i in items], [True, True, False, False, False])
            self.assertAlmostEqual(mp.rate(items), 0.4)
            self.assertEqual(items[2].errors[0][0], "schema_version")
            self.assertEqual(items[3].errors[0][0], "(extract)")
            self.assertEqual(items[4].errors[0][0], "(yaml)")

    def test_cli_threshold_and_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "a.yaml").write_text(SONG_OK, encoding="utf-8")
            code, out, _ = self.run_main(str(d), "--kind", "song")
            self.assertEqual(code, 0)
            self.assertIn("1/1 = 100%", out)
            (d / "b.yaml").write_text("title: x\n", encoding="utf-8")
            code, out, _ = self.run_main(str(d), "--kind", "song")
            self.assertEqual(code, 1)
            self.assertIn("未達", out)
            code, _, _ = self.run_main(str(d), "--kind", "song", "--threshold", "0.5")
            self.assertEqual(code, 0)

    def test_auto_kind_and_errors(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.yaml").write_text(SPEC_OK, encoding="utf-8")  # seed があるので spec と判断
            self.assertTrue(mp.measure([d])[0].ok)
            empty = Path(d) / "empty"
            empty.mkdir()
            self.assertEqual(self.run_main(str(empty))[0], 2)
            self.assertEqual(self.run_main(str(Path(d) / "none.yaml"))[0], 2)
            self.assertEqual(mp.rate([]), 0.0)

    def test_shipped_files_pass(self):
        items = mp.measure([str(ROOT / "songs"), str(ROOT / "specs")])
        self.assertTrue(items and all(i.ok for i in items))


class TemplatesTest(unittest.TestCase):
    def test_templates_contain_required_parts(self):
        for name in ("compose", "revise", "review"):
            text = (ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8")
            for needle in ("schemas/", "schema_version: 1", "validate", "check", "{漢字|よみ}", "音名:拍数", "~", "`r`", "|"):
                self.assertIn(needle, text, f"{name}.md に {needle!r} がありません")
        for name in ("compose", "revise"):
            text = (ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8")
            self.assertIn("YAML のみ", text)

    def test_claude_md_links_prompts(self):
        text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        for name in ("compose", "revise", "review"):
            self.assertIn(f"prompts/{name}.md", text)


if __name__ == "__main__":
    unittest.main()
