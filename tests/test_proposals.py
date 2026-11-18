import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from musicai import app, service
from musicai.history import History
from musicai.proposals import ProposalConflict, ProposalError, Proposals
from tests.test_history import SONG_V1, SONG_V2, RepoCase, git


class ProposalsCase(RepoCase):
    """一時フォルダの Git リポジトリに songs/s.yaml がある状態。"""

    def setUp(self):
        super().setUp()
        self.p = Proposals(self.root / "proposals", self.songs)

    def submit(self, text=SONG_V2, title="テンポを上げる", reason="サビを盛り上げるため"):
        return self.p.submit("s", text, title, reason)

    def song_text(self):
        return (self.songs / "s.yaml").read_text(encoding="utf-8")


class SubmitTest(ProposalsCase):
    def test_submit_keeps_song_untouched(self):
        r = self.submit()
        self.assertEqual((r["id"], r["status"], r["stale"]), (1, "pending", False))
        self.assertEqual(r["summary"], "歌詞 A／テンポ")
        self.assertEqual(self.song_text(), SONG_V1)  # 提案しただけでは曲は変わらない
        self.assertEqual(self.h.list_versions("s"), [])  # 履歴にも載らない
        self.assertEqual(self.submit(title="2つ目")["id"], 2)
        self.assertEqual([x["id"] for x in self.p.list("s")], [2, 1])

    def test_submit_adds_schema_version_and_keeps_comments(self):
        r = self.submit(SONG_V2.replace("schema_version: 1\n", "# 理由のメモ\n"))
        text = self.p.yaml_of("s", r["id"])
        self.assertIn("# 理由のメモ", text)
        self.assertEqual(yaml.safe_load(text)["schema_version"], 1)

    def test_submit_validation(self):
        bad = [(SONG_V2, "", "タイトル"), (SONG_V2, "x" * 81, "80"), ("a: [", "t", "読めません"),
               ("- 1\n", "t", "曲のデータ"), (SONG_V2.replace("tempo", "tempoo"), "t", "tempoo"),
               (SONG_V1, "t", "同じ内容"), ("x" * 1_000_001, "t", "大きすぎ"),
               ("schema_version: 1\nsections:\n  A:\n    chords: ZZZ\n", "t", "曲として読めません")]
        for text, title, word in bad:
            with self.assertRaises(ProposalError, msg=word) as cm:
                self.p.submit("s", text, title)
            self.assertIn(word, str(cm.exception))
        with self.assertRaises(ProposalError):
            self.p.submit("none", SONG_V2, "t")
        with self.assertRaises(ProposalError):
            self.p.submit("s", SONG_V2, "t", "r" * 2001)
        self.assertEqual(self.p.list("s"), [])  # 失敗したものは残らない

    def test_check_warnings_are_kept_not_blocking(self):
        mismatch = SONG_V1.replace("あいうえお", "あいう")
        r = self.submit(mismatch)
        self.assertTrue(r["warnings"])

    def test_song_name_cannot_escape(self):
        with self.assertRaises(ProposalError):
            self.p.submit("../../etc/passwd", SONG_V2, "t")
        self.assertFalse((self.root / "etc").exists())
        self.assertEqual(self.p.list("../x"), [])


class DetailTest(ProposalsCase):
    def test_get_has_lyrics_diff_against_current(self):
        r = self.submit()
        d = self.p.get("s", r["id"])
        secs = {s["name"]: s for s in d["lyrics"]}
        self.assertTrue(secs["A"]["changed"])
        self.assertEqual([x["type"] for x in secs["A"]["lines"]], ["same", "change", "add"])
        with self.assertRaises(ProposalError):
            self.p.get("s", 99)

    def test_stale_when_song_changes_after_proposal(self):
        r = self.submit()
        (self.songs / "s.yaml").write_text(SONG_V1.replace("title: t", "title: u"), encoding="utf-8")
        self.assertTrue(self.p.list("s")[0]["stale"])
        self.assertTrue(self.p.get("s", r["id"])["stale"])

    def test_broken_file_is_skipped(self):
        self.submit()
        (self.root / "proposals" / "s" / "0009.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(len(self.p.list("s")), 1)


class AdoptRejectTest(ProposalsCase):
    def test_adopt_writes_song_and_saves_version(self):
        r = self.submit(title="歌詞を変える")
        res = self.p.adopt("s", r["id"], self.h)
        self.assertTrue(res["adopted"])
        self.assertEqual(self.song_text(), self.p.yaml_of("s", r["id"]))
        vs = self.h.list_versions("s")
        self.assertEqual([v.note for v in vs], ["提案の採用前の自動保存", "提案を採用: 歌詞を変える"])
        self.assertEqual((res["auto_saved"], res["version"]), (1, 2))
        old = self.h.lyrics_diff("s", 1, 2)["sections"][0]["lines"]  # バージョン 1 = 採用前の内容
        self.assertEqual(old[1], {"type": "change", "old": "かきくけこ", "new": "たちつてと"})
        got = self.p.list("s")[0]
        self.assertEqual((got["status"], got["adopted_version"]), ("adopted", 2))

    def test_only_adoption_creates_a_version(self):
        a, b = self.submit(), self.submit(SONG_V2.replace("tempo: 120", "tempo: 90"), "別案")
        self.p.reject("s", b["id"])
        self.assertEqual(self.h.list_versions("s"), [])  # 提案・却下では履歴に載らない
        self.assertEqual(self.song_text(), SONG_V1)
        self.p.adopt("s", a["id"], self.h)
        self.assertEqual(len(self.h.list_versions("s")), 2)

    def test_adopt_without_git_still_works(self):
        r = self.submit()
        with mock.patch("musicai.history.shutil.which", return_value=None):
            res = self.p.adopt("s", r["id"], self.h)
        self.assertTrue(res["adopted"])
        self.assertIsNone(res["version"])
        self.assertIn("履歴機能は使えない", res["message"])
        self.assertEqual(self.song_text(), self.p.yaml_of("s", r["id"]))
        r2 = self.submit(SONG_V2.replace("tempo: 120", "tempo: 70"), "もう 1 つ")  # 履歴なしの環境でも提案は使える
        self.assertEqual(self.p.reject("s", r2["id"])["rejected"], True)

    def test_adopt_with_history_none(self):
        r = self.submit()
        self.assertIsNone(self.p.adopt("s", r["id"], None)["version"])

    def test_stale_proposal_cannot_be_adopted(self):
        r = self.submit()
        changed = SONG_V1.replace("title: t", "title: u")
        (self.songs / "s.yaml").write_text(changed, encoding="utf-8")
        with self.assertRaises(ProposalConflict):
            self.p.adopt("s", r["id"], self.h)
        self.assertEqual(self.song_text(), changed)  # 何も変わらない
        self.assertEqual(self.p.list("s")[0]["status"], "pending")

    def test_cannot_decide_twice_and_errors(self):
        r = self.submit()
        self.p.reject("s", r["id"])
        for fn in (lambda: self.p.adopt("s", r["id"], self.h), lambda: self.p.reject("s", r["id"])):
            with self.assertRaises(ProposalError) as cm:
                fn()
            self.assertIn("却下", str(cm.exception))
        with self.assertRaises(ProposalError):
            self.p.adopt("s", 99, self.h)
        r2 = self.submit(title="消える曲")
        (self.songs / "s.yaml").unlink()
        with self.assertRaises(ProposalError):
            self.p.adopt("s", r2["id"], self.h)

    def test_adopt_commits_only_the_song_file(self):
        (self.root / "other.txt").write_text("o", encoding="utf-8")
        git(self.root, "add", "other.txt")
        r = self.submit()
        self.p.adopt("s", r["id"], self.h)
        self.assertEqual(git(self.root, "show", "--name-only", "--format=", "HEAD").split(), ["songs/s.yaml"])
        self.assertIn("other.txt", git(self.root, "diff", "--cached", "--name-only"))


class ConflictAdoptTest(ProposalsCase):
    """提案を出したあとに、曲が変わった場合（C4）。"""

    def setUp(self):
        super().setUp()
        self.r = self.submit(SONG_V1.replace("tempo: 100", "tempo: 120"), "テンポ案")  # 提案: テンポだけ
        # 自分: 曲名を変え、A の歌詞も変えた（提案とは重ならない）
        (self.songs / "s.yaml").write_text(SONG_V1.replace("title: t", "title: 自分の題"), encoding="utf-8")

    def test_non_overlapping_changes_merge_automatically(self):
        self.assertTrue(self.p.list("s")[0]["stale"])
        plan = self.p.conflicts("s", self.r["id"])
        self.assertEqual((plan["stale"], plan["conflicts"]), (True, []))
        res = self.p.adopt("s", self.r["id"], self.h, {})
        self.assertTrue(res["adopted"])
        out = yaml.safe_load(self.song_text())
        self.assertEqual((out["title"], out["tempo"]), ("自分の題", 120))  # 自分の変更と提案の両方
        notes = [v.note for v in self.h.list_versions("s")]
        self.assertEqual(notes, ["提案の採用前の自動保存", "提案を採用（衝突を解決）: テンポ案"])

    def test_overlap_needs_choice_and_choice_is_applied(self):
        (self.songs / "s.yaml").write_text(SONG_V1.replace("tempo: 100", "tempo: 80"), encoding="utf-8")
        plan = self.p.conflicts("s", self.r["id"])
        self.assertEqual(plan["conflicts"], ["meta:tempo"])
        with self.assertRaises(ProposalConflict):
            self.p.adopt("s", self.r["id"], self.h)            # 選択なし
        with self.assertRaises(ProposalConflict) as cm:
            self.p.adopt("s", self.r["id"], self.h, {})         # 衝突が未選択
        self.assertIn("テンポ", str(cm.exception))
        self.assertEqual(yaml.safe_load(self.song_text())["tempo"], 80)  # ここまで曲は変わっていない
        self.assertEqual(self.p.list("s")[0]["status"], "pending")
        self.p.adopt("s", self.r["id"], self.h, {"meta:tempo": "theirs"})
        self.assertEqual(yaml.safe_load(self.song_text())["tempo"], 120)

    def test_choose_mine_keeps_song_content(self):
        (self.songs / "s.yaml").write_text(SONG_V1.replace("tempo: 100", "tempo: 80"), encoding="utf-8")
        with self.assertRaises(ProposalError) as cm:  # 全部「自分の版」を選ぶと、変わるところが無い
            self.p.adopt("s", self.r["id"], self.h, {"meta:tempo": "mine"})
        self.assertIn("却下", str(cm.exception))
        self.assertEqual(self.p.list("s")[0]["status"], "pending")  # 提案は検討中のまま
        self.assertEqual(yaml.safe_load(self.song_text())["tempo"], 80)

    def test_proposal_already_contained_in_song(self):
        (self.songs / "s.yaml").write_text(SONG_V1.replace("tempo: 100", "tempo: 120"), encoding="utf-8")  # 同じ変更を自分でも
        with self.assertRaises(ProposalError) as cm:
            self.p.adopt("s", self.r["id"], self.h, {})
        self.assertIn("同じ内容", str(cm.exception))

    def test_conflicts_errors(self):
        self.p.reject("s", self.r["id"])
        with self.assertRaises(ProposalError):
            self.p.conflicts("s", self.r["id"])
        with self.assertRaises(ProposalError):
            self.p.conflicts("s", 99)

    def test_api(self):
        with mock.patch.multiple(service, DATA_DIR=self.root, SONGS_DIR=self.songs,
                                 PROPOSALS_DIR=self.root / "proposals", OUTPUT_DIR=self.root / "output"):
            plan = app.api_proposal_conflicts({"song": ["s"], "id": [str(self.r["id"])]}, {})
            self.assertTrue(plan["stale"])
            for bad in ("mine", ["x"], {"a": 1}):
                with self.assertRaises(ValueError):
                    app.api_proposal_adopt({}, {"song": "s", "id": self.r["id"], "choices": bad})
            res = app.api_proposal_adopt({}, {"song": "s", "id": self.r["id"], "choices": {}})
            self.assertTrue(res["adopted"])


class ApiTest(ProposalsCase):
    def setUp(self):
        super().setUp()
        self._pp = mock.patch.multiple(service, DATA_DIR=self.root, SONGS_DIR=self.songs,
                                       PROPOSALS_DIR=self.root / "proposals", OUTPUT_DIR=self.root / "output")
        self._pp.start()

    def tearDown(self):
        self._pp.stop()
        super().tearDown()

    def test_flow_and_no_git_terms(self):
        r = app.api_proposal_submit({}, {"song": "s", "yaml": SONG_V2, "title": "案", "reason": "理由"})
        self.assertEqual(app.api_proposals({"song": ["s"]}, {})["proposals"][0]["id"], r["id"])
        d = app.api_proposal({"song": ["s"], "id": [str(r["id"])]}, {})
        a = app.api_proposal_adopt({}, {"song": "s", "id": r["id"]})
        blob = json.dumps([r, d, a, app.api_proposals({"song": ["s"]}, {})], ensure_ascii=False)
        self.assertNotRegex(blob, r"[0-9a-f]{7,40}")
        for w in ("commit", "branch", "hash"):
            self.assertNotIn(w, blob.lower())
        self.assertEqual(self.song_text(), self.p.yaml_of("s", r["id"]))

    def test_reject_and_errors(self):
        r = app.api_proposal_submit({}, {"song": "s", "yaml": SONG_V2, "title": "案"})
        self.assertTrue(app.api_proposal_reject({}, {"song": "s", "id": r["id"]})["rejected"])
        with self.assertRaises(ValueError):
            app.api_proposal_adopt({}, {"song": "s", "id": r["id"]})
        with self.assertRaises(ValueError):
            app.api_proposal_adopt({}, {"song": "s", "id": "x"})

    def test_render_for_preview_leaves_song_alone(self):
        r = app.api_proposal_submit({}, {"song": "s", "yaml": SONG_V2, "title": "案"})
        out = app.api_proposal_render({}, {"song": "s", "id": r["id"], "mute": ["vocal"]})
        self.assertTrue(out["files"]["midi"].startswith("s_提案1_vocal"))
        self.assertTrue((self.root / "output" / out["files"]["midi"]).is_file())
        self.assertEqual(self.song_text(), SONG_V1)

    def test_cli(self):
        import contextlib, io
        from musicai.__main__ import main
        f = self.root / "p.yaml"
        f.write_text(SONG_V2, encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            main(["propose", "s", "--yaml", str(f), "--title", "CLI 案", "--reason", "r"])
            main(["proposals", "s"])
        self.assertIn("提案 1 を出しました", buf.getvalue())
        self.assertIn("CLI 案", buf.getvalue())
        self.assertEqual(self.song_text(), SONG_V1)
        (self.songs / "s.yaml").write_text(SONG_V1.replace("title: t", "title: u"), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            main(["proposals", "s"])
            main(["proposals", "nothing"])
        self.assertIn("変わっています", buf.getvalue())
        self.assertIn("提案はありません", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
