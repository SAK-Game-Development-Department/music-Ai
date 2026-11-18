import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from musicai import history
from musicai.history import History, HistoryError, HistoryUnavailable, diff_lyrics, summarize_change

SONG_V1 = """schema_version: 1
title: t
tempo: 100
sections:
  A:
    chords: C | F
    melody: C4:1 D4
    lyrics: |
      あいうえお
      かきくけこ
  B:
    lyrics: さしすせそ
"""
SONG_V2 = SONG_V1.replace("かきくけこ", "たちつてと\n  なにぬねの".replace("\n  ", "\n      ")).replace("tempo: 100", "tempo: 120")


def git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "dev", "GIT_AUTHOR_EMAIL": "d@x", "GIT_COMMITTER_NAME": "dev",
           "GIT_COMMITTER_EMAIL": "d@x", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


@unittest.skipUnless(shutil.which("git"), "git が無い環境では履歴のテストを飛ばす")
class RepoCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        git(self.root, "init", "-q")
        self.songs = self.root / "songs"
        self.songs.mkdir()
        self.h = History(self.songs)
        # 開発用のコミット（バージョンには出ない）
        (self.root / "README.md").write_text("x", encoding="utf-8")
        (self.songs / "s.yaml").write_text(SONG_V1, encoding="utf-8")
        git(self.root, "add", "."); git(self.root, "commit", "-q", "-m", "dev commit")
        # このテストでは利用者の git 設定が無い環境を再現する
        self._env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull})
        self._env.start()
        for k in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
            os.environ.pop(k, None)

    def tearDown(self):
        self._env.stop()
        self._td.cleanup()


class VersionTest(RepoCase):
    def test_available_and_empty(self):
        self.assertTrue(self.h.available())
        self.assertEqual(self.h.status(), {"available": True, "message": ""})
        self.assertEqual(self.h.list_versions("s"), [])  # 開発コミットはバージョンではない

    def test_save_list_and_summary(self):
        r = self.h.save_version("s", "最初の案")
        self.assertEqual((r["saved"], r["no"]), (True, 1))
        again = self.h.save_version("s", "同じ")
        self.assertFalse(again["saved"])  # 変更なしなら載せない
        (self.songs / "s.yaml").write_text(SONG_V2, encoding="utf-8")
        self.assertTrue(self.h.save_version("s")["saved"])
        vs = self.h.list_versions("s")
        self.assertEqual([v.no for v in vs], [1, 2])
        self.assertEqual((vs[0].note, vs[1].note), ("最初の案", ""))
        self.assertEqual(vs[0].summary, "最初のバージョン")
        self.assertEqual(vs[1].summary, "歌詞 A／テンポ")
        self.assertTrue(vs[1].at.startswith("20"))

    def test_only_target_file_is_committed(self):
        (self.root / "other.txt").write_text("o", encoding="utf-8")
        git(self.root, "add", "other.txt")  # staged の別ファイル
        (self.songs / "t.yaml").write_text(SONG_V1, encoding="utf-8")  # 未追跡の新曲
        self.h.save_version("t", "x")
        changed = git(self.root, "show", "--name-only", "--format=", "HEAD").split()
        self.assertEqual(changed, ["songs/t.yaml"])
        self.assertIn("other.txt", git(self.root, "diff", "--cached", "--name-only"))  # staged のまま残る

    def test_songs_are_independent(self):
        (self.songs / "t.yaml").write_text(SONG_V1, encoding="utf-8")
        self.h.save_version("s"); self.h.save_version("t")
        (self.songs / "t.yaml").write_text(SONG_V2, encoding="utf-8")
        self.h.save_version("t")
        self.assertEqual(len(self.h.list_versions("s")), 1)
        self.assertEqual(len(self.h.list_versions("t")), 2)

    def test_errors(self):
        with self.assertRaises(HistoryError):
            self.h.save_version("missing")
        for bad in ("", "../x", "a/b", ".hidden"):
            with self.assertRaises(HistoryError):
                self.h.list_versions(bad)
        self.h.save_version("s")
        with self.assertRaises(HistoryError):
            self.h.lyrics_diff("s", 1, 2)

    def test_lyrics_diff_between_versions(self):
        self.h.save_version("s")
        (self.songs / "s.yaml").write_text(SONG_V2, encoding="utf-8")
        self.h.save_version("s")
        d = self.h.lyrics_diff("s", 1, 2)
        secs = {s["name"]: s for s in d["sections"]}
        self.assertTrue(secs["A"]["changed"])
        self.assertFalse(secs["B"]["changed"])
        self.assertEqual([x["type"] for x in secs["A"]["lines"]], ["same", "change", "add"])
        self.assertEqual(secs["A"]["lines"][1], {"type": "change", "old": "かきくけこ", "new": "たちつてと"})
        self.assertEqual((d["a"]["no"], d["b"]["no"]), (1, 2))

    def test_no_git_terms_in_responses(self):
        self.h.save_version("s", "メモ")
        (self.songs / "s.yaml").write_text(SONG_V2, encoding="utf-8")
        self.h.save_version("s")
        blob = json.dumps({"s": self.h.status(), "v": [v.to_dict() for v in self.h.list_versions("s")],
                           "d": self.h.lyrics_diff("s", 1, 2), "r": self.h.save_version("s")}, ensure_ascii=False)
        self.assertNotRegex(blob, r"[0-9a-f]{7,40}")
        for word in ("commit", "branch", "hash", "Musicai-Version", "git"):
            self.assertNotIn(word, blob.lower() if word.islower() else blob)

    def test_renamed_song_starts_new_history(self):
        self.h.save_version("s", "旧名")
        git(self.root, "mv", "songs/s.yaml", "songs/u.yaml")
        git(self.root, "commit", "-q", "-m", "rename")
        self.assertEqual(self.h.list_versions("u"), [])
        self.h.save_version("u", "新名")
        self.assertEqual([v.note for v in self.h.list_versions("u")], ["新名"])
        self.assertEqual([v.note for v in self.h.list_versions("s")], ["旧名"])

    def test_unchanged_since_dev_commit_can_still_be_versioned(self):
        # setUp で s.yaml は開発用コミット済み。差分が無くても最初のバージョンが作れる
        self.assertTrue(self.h.save_version("s")["saved"])
        self.assertEqual(len(self.h.list_versions("s")), 1)


class RestoreTest(RepoCase):
    def v(self, text, note=""):
        (self.songs / "s.yaml").write_text(text, encoding="utf-8")
        return self.h.save_version("s", note)

    def test_restore_adds_new_version_and_keeps_history(self):
        self.v(SONG_V1, "元")
        self.v(SONG_V2, "変更")
        r = self.h.restore_version("s", 1)
        self.assertEqual((r["restored"], r["no"], r["auto_saved"]), (True, 3, None))
        self.assertEqual((self.songs / "s.yaml").read_text(encoding="utf-8"), SONG_V1)
        vs = self.h.list_versions("s")
        self.assertEqual([v.no for v in vs], [1, 2, 3])  # 巻き戻さず、足される
        self.assertEqual(vs[2].note, "バージョン 1 に戻した")
        self.assertEqual(vs[2].summary, "歌詞 A／テンポ")  # 前（2）との差
        self.assertEqual(self.h.read_version("s", 2), SONG_V2)  # 古い版はそのまま読める

    def test_unsaved_work_is_kept_as_automatic_version(self):
        self.v(SONG_V1, "元")
        self.v(SONG_V2, "変更")
        work = SONG_V2.replace("tempo: 120", "tempo: 90")  # まだバージョンにしていない作業中の変更
        (self.songs / "s.yaml").write_text(work, encoding="utf-8")
        r = self.h.restore_version("s", 1)
        self.assertEqual((r["restored"], r["auto_saved"], r["no"]), (True, 3, 4))
        vs = self.h.list_versions("s")
        self.assertEqual([v.note for v in vs][2:], ["復元前の自動保存", "バージョン 1 に戻した"])
        self.assertEqual(self.h.read_version("s", 3), work)  # 作業中の内容は失われていない
        self.assertEqual((self.songs / "s.yaml").read_text(encoding="utf-8"), SONG_V1)

    def test_noop_and_errors(self):
        self.v(SONG_V1)
        r = self.h.restore_version("s", 1)  # すでに同じ内容
        self.assertEqual((r["restored"], r["no"]), (False, 1))
        self.assertEqual(len(self.h.list_versions("s")), 1)
        for bad in (0, 2, -1):
            with self.assertRaises(HistoryError):
                self.h.restore_version("s", bad)
            with self.assertRaises(HistoryError):
                self.h.read_version("s", bad)

    def test_restore_deleted_file_and_only_that_file(self):
        self.v(SONG_V1, "元")
        (self.songs / "s.yaml").unlink()
        (self.root / "other.txt").write_text("o", encoding="utf-8")
        git(self.root, "add", "other.txt")
        r = self.h.restore_version("s", 1)
        self.assertTrue(r["restored"])
        self.assertEqual((self.songs / "s.yaml").read_text(encoding="utf-8"), SONG_V1)
        # 内容は最新バージョンと同じなので、記録だけが増える。ほかの staged ファイルは巻き込まない
        self.assertEqual(git(self.root, "show", "--name-only", "--format=", "HEAD").split(), [])
        self.assertIn("other.txt", git(self.root, "diff", "--cached", "--name-only"))
        self.assertEqual([v.note for v in self.h.list_versions("s")], ["元", "バージョン 1 に戻した"])

    def test_responses_have_no_git_terms(self):
        self.v(SONG_V1); self.v(SONG_V2)
        blob = json.dumps([self.h.restore_version("s", 1), [v.to_dict() for v in self.h.list_versions("s")]],
                          ensure_ascii=False)
        self.assertNotRegex(blob, r"[0-9a-f]{7,40}")
        for word in ("commit", "branch", "hash", "reset", "revert"):
            self.assertNotIn(word, blob.lower())


class UnavailableTest(unittest.TestCase):
    def test_outside_repo(self):
        with tempfile.TemporaryDirectory() as d:
            songs = Path(d) / "songs"
            songs.mkdir()
            (songs / "s.yaml").write_text(SONG_V1, encoding="utf-8")
            h = History(songs)
            with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": d}):
                self.assertEqual(h.status(), {"available": False, "message": "履歴機能は使えません"})
                with self.assertRaises(HistoryUnavailable):
                    h.list_versions("s")
                with self.assertRaises(HistoryUnavailable):
                    h.save_version("s")

    def test_git_not_installed(self):
        with tempfile.TemporaryDirectory() as d:
            h = History(d)
            with mock.patch.object(history.shutil, "which", return_value=None):
                self.assertFalse(h.available())
                with self.assertRaises(HistoryUnavailable):
                    h.list_versions("s")

    def test_missing_songs_dir(self):
        self.assertFalse(History("/nonexistent/songs").available())

    def test_git_crash(self):
        with mock.patch.object(history.subprocess, "run", side_effect=OSError("x")):
            self.assertFalse(History(".").available())


class PureFunctionTest(unittest.TestCase):
    def test_diff_kinds(self):
        a = "sections:\n  A:\n    lyrics: |\n      い\n      ろ\n      は\n  C:\n    lyrics: ぬ\n"
        b = "sections:\n  A:\n    lyrics: 'い / に / は / ほ'\n  D:\n    lyrics: へ\n"
        secs = {s["name"]: s for s in diff_lyrics(a, b)}
        self.assertEqual([x["type"] for x in secs["A"]["lines"]], ["same", "change", "same", "add"])
        self.assertEqual(secs["C"]["status"], "removed")
        self.assertEqual(secs["C"]["lines"], [{"type": "remove", "text": "ぬ"}])
        self.assertEqual(secs["D"]["status"], "added")
        self.assertEqual(secs["D"]["lines"], [{"type": "add", "text": "へ"}])

    def test_diff_replace_uneven_and_delete(self):
        a = "sections:\n  A:\n    lyrics: 'a / b / c'\n"
        b = "sections:\n  A:\n    lyrics: 'x'\n"
        lines = diff_lyrics(a, b)[0]["lines"]
        self.assertEqual([x["type"] for x in lines], ["change", "remove", "remove"])
        lines = diff_lyrics(a, "sections:\n  A:\n    lyrics: 'a / c'\n")[0]["lines"]
        self.assertEqual([x["type"] for x in lines], ["same", "remove", "same"])

    def test_diff_tolerates_broken_input(self):
        self.assertEqual(diff_lyrics("a: [1,", "- 1"), [])
        self.assertEqual(diff_lyrics("sections:\n  A: null\n  B: x\n", "sections:\n  A:\n    lyrics: 5\n"), [])

    def test_summary(self):
        base = SONG_V1
        self.assertEqual(summarize_change(base, base), "変更なし（細かい書き方の違いのみ）")
        s = summarize_change(base, base.replace("C4:1 D4", "C4:1 E4").replace("C | F", "C | G")
                             .replace("style", "x") + "style: ballad\nstructure: [A]\n")
        for word in ("メロディ A", "コード A", "アレンジ", "構成"):
            self.assertIn(word, s)
        s = summarize_change(base, base.replace("  B:\n    lyrics: さしすせそ\n", "  C:\n    energy: high\n"))
        self.assertIn("追加 C", s); self.assertIn("削除 B", s)
        s = summarize_change(base + "  C:\n    energy: low\n", base + "  C:\n    energy: high\n")
        self.assertIn("設定 C", s)
        self.assertIn("タイトル", summarize_change(base, base.replace("title: t", "title: u")))
        self.assertEqual(summarize_change("- 1", "- 2"), "変更なし（細かい書き方の違いのみ）")


if __name__ == "__main__":
    unittest.main()
