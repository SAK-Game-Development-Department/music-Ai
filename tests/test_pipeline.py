import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from musicai import pipeline, service, tools
from musicai.pipeline import PipelineError
from musicai.tools import ToolError
from tests.test_history import RepoCase
from tests.test_tools import MISMATCH, ROOT, SPEC, ToolsCase


def tree(base: Path):
    """songs/ と output/ の中身（名前 → 内容）。変わっていないことの確認用。"""
    return {p.relative_to(base).as_posix(): p.read_bytes() for d in ("songs", "output") for p in sorted((base / d).rglob("*"))
            if p.is_file()}


def leftovers(base: Path):
    return [p.name for p in base.iterdir() if p.name.startswith(".musicai-staging-")]


class SuccessTest(ToolsCase):
    def test_compose_runs_all_steps(self):
        r = tools.call("make_song", {"mode": "compose", "spec": SPEC, "name": "新曲"})
        self.assertEqual(r["steps"], ["作曲", "検証（validate）", "検査（check）", "書き出し", "反映"])
        self.assertEqual((r["name"], r["path"]), ("新曲", "songs/新曲.yaml"))
        self.assertEqual(set(r["files"]), {"midi", "musicxml", "lyrics"})
        for rel in [r["path"], *r["files"].values()]:
            self.assertTrue((self.base / rel).is_file(), rel)
        self.assertTrue(tools.call("validate", {"name": "新曲", "check": True})["ok"])
        self.assertEqual(leftovers(self.base), [])  # 一時フォルダは残らない
        self.assertFalse((self.base / "output" / "新曲.wav").exists())  # 頼んでいない形式は反映しない

    def test_kaeuta_mode_and_wav(self):
        r = tools.call("make_song", {"mode": "kaeuta", "song": "hoshi", "lyrics": {"A": "ラーメンたべたい / チャーシューおおめで"},
                                     "formats": ["wav"]})
        self.assertEqual((r["name"], list(r["files"])), ("hoshi_kaeuta", ["wav"]))
        self.assertTrue(r["report"])
        self.assertTrue((self.base / r["files"]["wav"]).is_file())
        self.assertFalse((self.base / "output" / "hoshi_kaeuta.mid").exists())

    def test_missing_formats_note(self):
        real = service.render_song
        with mock.patch.object(service, "render_song",
                               side_effect=lambda *a, **k: {x: y for x, y in real(*a, **k).items() if x != "mp3"}):
            r = tools.call("make_song", {"mode": "compose", "spec": SPEC, "formats": ["mp3", "midi"]})
        self.assertEqual(list(r["files"]), ["midi"])
        self.assertIn("ffmpeg", r["note"])


class FailureLeavesNothingTest(ToolsCase):
    def check_untouched(self, args, step, word):
        before = tree(self.base)
        with self.assertRaises(PipelineError) as cm:
            tools.call("make_song", args)
        self.assertEqual(cm.exception.step, step)
        self.assertIn(word, str(cm.exception))
        self.assertIn("変更していません", str(cm.exception))
        self.assertEqual(tree(self.base), before)  # songs/ と output/ は 1 バイトも変わらない
        self.assertEqual(leftovers(self.base), [])
        return cm.exception

    def test_generation_failure(self):
        e = self.check_untouched({"mode": "compose", "spec": {**SPEC, "sections": {"v": {"progresion": "I"}}}}, "作曲", "progresion")
        self.assertEqual(e.steps, [])
        self.check_untouched({"mode": "kaeuta", "song": "none", "lyrics": {"A": "あ"}}, "替え歌", "見つかりません")

    def test_existing_song_without_overwrite(self):
        self.check_untouched({"mode": "compose", "spec": SPEC, "name": "hoshi"}, "作曲", "overwrite")

    def test_check_failure_stops_before_export(self):
        self.put("m", "schema_version: 1\nkey: C major\ntempo: 100\nsections:\n"
                      "  A:\n    chords: C\n    melody: C4:2 D4:2\n    lyrics: あい\n"
                      "  B:\n    chords: C\n    melody: C4:2 D4:2\n    lyrics: あいう\n")
        # A は合うが B は合わない曲に替え歌を付ける → B の警告が残るので、警告ゼロにならない
        e = self.check_untouched({"mode": "kaeuta", "song": "m", "lyrics": {"A": "さし"}}, "検査（check）", "警告")
        self.assertEqual(e.steps, ["替え歌", "検証（validate）"])
        r = tools.call("make_song", {"mode": "kaeuta", "song": "m", "lyrics": {"A": "さし"}, "allow_warnings": True})
        self.assertTrue(r["warnings"])  # allow_warnings なら進む

    def test_export_failure(self):
        with mock.patch.object(service, "render_song", side_effect=RuntimeError("boom")), \
                mock.patch("traceback.print_exc"):
            e = self.check_untouched({"mode": "compose", "spec": SPEC}, "書き出し", "boom")
        self.assertEqual(e.steps, ["作曲", "検証（validate）", "検査（check）"])

    def test_export_failure_keeps_existing_song_on_overwrite(self):
        original = (self.base / "songs" / "hoshi.yaml").read_bytes()
        with mock.patch.object(service, "render_song", side_effect=OSError("disk")), mock.patch("traceback.print_exc"):
            with self.assertRaises(PipelineError):
                tools.call("make_song", {"mode": "compose", "spec": SPEC, "name": "hoshi", "overwrite": True})
        self.assertEqual((self.base / "songs" / "hoshi.yaml").read_bytes(), original)


class RollbackTest(ToolsCase):
    def test_failure_in_the_middle_of_commit_restores_everything(self):
        # 既存の曲と、同名の書き出しファイルがある状態で、3 つ目の入れ替えに失敗させる
        (self.base / "output" / "hoshi.mid").write_bytes(b"OLD-MID")
        (self.base / "output" / "hoshi.musicxml").write_bytes(b"OLD-XML")
        before = tree(self.base)
        calls = {"n": 0}
        real_replace = os.replace

        def flaky(src, dst):
            if str(dst).startswith(str(self.base)) and ".musicai-staging-" in str(src):
                calls["n"] += 1
                if calls["n"] == 3:
                    raise OSError("入れ替えに失敗")
            return real_replace(src, dst)

        with mock.patch.object(pipeline.os, "replace", side_effect=flaky), mock.patch("traceback.print_exc"):
            with self.assertRaises(PipelineError) as cm:
                tools.call("make_song", {"mode": "compose", "spec": SPEC, "name": "hoshi", "overwrite": True})
        self.assertTrue(cm.exception.rolled_back)
        self.assertIn("元の状態に戻しました", str(cm.exception))
        self.assertEqual(calls["n"], 3)
        self.assertEqual(tree(self.base), before)  # 曲も、書き出しも、すべて元どおり
        self.assertEqual(leftovers(self.base), [])

    def test_commit_helper_removes_newly_created_files(self):
        stage = self.base / "stage"
        stage.mkdir()
        for i in range(3):
            (stage / f"f{i}").write_text(str(i))
        dsts = [self.base / "output" / f"n{i}" for i in range(3)]
        real_replace = os.replace
        n = {"c": 0}

        def flaky(src, dst):
            n["c"] += 1
            if n["c"] == 3:
                raise OSError("x")
            return real_replace(src, dst)

        with mock.patch.object(pipeline.os, "replace", side_effect=flaky), mock.patch("traceback.print_exc"):
            with self.assertRaises(OSError):
                pipeline._commit([(stage / f"f{i}", dsts[i]) for i in range(3)], self.base / "bk")
        self.assertEqual([d.exists() for d in dsts], [False, False, False])  # 新しく作ったものは消える


class SnapshotTest(RepoCase):
    def test_overwrite_saves_version_first(self):
        base = self.root
        (base / "output").mkdir()
        with mock.patch.multiple(service, DATA_DIR=base, SONGS_DIR=self.songs, SPECS_DIR=base / "specs",
                                 OUTPUT_DIR=base / "output"):
            r = pipeline.run({"mode": "compose", "spec": SPEC, "name": "s", "overwrite": True})
        self.assertEqual(r["snapshot_version"], 1)
        vs = self.h.list_versions("s")
        self.assertEqual([v.note for v in vs], ["自動作成の前の自動保存"])
        self.assertIn("あいうえお", self.h.lyrics_diff("s", 1, 1)["sections"][0]["lines"][0]["text"])  # 上書き前の内容が残っている

    def test_without_git_overwrite_still_works(self):
        base = self.root
        (base / "output").mkdir()
        with mock.patch.multiple(service, DATA_DIR=base, SONGS_DIR=self.songs, SPECS_DIR=base / "specs",
                                 OUTPUT_DIR=base / "output"), mock.patch("musicai.history.shutil.which", return_value=None):
            r = pipeline.run({"mode": "compose", "spec": SPEC, "name": "s", "overwrite": True})
        self.assertIsNone(r["snapshot_version"])


class CliAndToolTest(ToolsCase):
    def test_input_validation(self):
        for args in ({}, {"mode": "x"}, {"mode": "compose", "bogus": 1}, {"mode": "compose", "formats": ["ogg"]}):
            with self.assertRaises(ToolError):
                tools.call("make_song", args)
        with self.assertRaises(ToolError):  # compose に spec が無い
            tools.call("make_song", {"mode": "compose"})
        with self.assertRaises(ToolError):
            pipeline.run({"mode": "other"})

    def test_cli(self):
        import contextlib, io
        from musicai.__main__ import main
        spec = self.base / "sp.yaml"
        spec.write_text(yaml.safe_dump({"schema_version": 1, **SPEC}, allow_unicode=True), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            main(["pipeline", "compose", str(spec), "--name", "cli曲"])
        self.assertIn("反映", buf.getvalue())
        self.assertTrue((self.base / "songs" / "cli曲.yaml").is_file())
        with self.assertRaises(SystemExit) as cm:
            main(["pipeline", "compose", str(spec), "--name", "cli曲"])  # 同名は上書きしない
        self.assertIn("overwrite", str(cm.exception))
        lyr = self.base / "l.yaml"
        lyr.write_text("A: らーめん / たべたい\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            main(["pipeline", "kaeuta", "hoshi", "--lyrics-file", str(lyr), "--name", "cli替"])
        self.assertTrue((self.base / "songs" / "cli替.yaml").is_file())


if __name__ == "__main__":
    unittest.main()
