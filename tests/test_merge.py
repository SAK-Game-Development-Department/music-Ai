import copy
import unittest

import yaml

from musicai import merge
from musicai.merge import MergeError
from musicai.service import dump_yaml

BASE = {"schema_version": 1, "title": "t", "key": "C major", "tempo": 100, "style": "pop", "structure": ["A", "B"],
        "sections": {"A": {"chords": "C | F", "melody": "C4:2 D4:2 | E4:4", "lyrics": "あい / うえ"},
                     "B": {"chords": "G | C", "melody": "G4:2 A4:2 | C5:4", "lyrics": "かき / くけ"}}}


def mk(**changes):
    d = copy.deepcopy(BASE)
    for k, v in changes.items():
        if k.startswith("A_") or k.startswith("B_"):
            d["sections"][k[0]][k[2:]] = v
        else:
            d[k] = v
    return dump_yaml(d)


def load(text):
    return yaml.safe_load(text)


class AnalyzeTest(unittest.TestCase):
    def test_disjoint_changes_merge_automatically(self):
        cur = mk(A_lyrics="あいうえ")           # 自分: A の歌詞
        prop = mk(B_melody="G4:4 | C5:4", tempo=120)  # 提案: B のメロディとテンポ
        plan = merge.analyze(mk(), cur, prop)
        self.assertEqual(plan["conflicts"], [])
        dec = {u["id"]: u["decision"] for u in plan["units"]}
        self.assertEqual(dec, {"meta:tempo": "theirs", "section:A": "mine", "section:B": "theirs"})
        out = load(merge.resolve(mk(), cur, prop, None))
        self.assertEqual(out["sections"]["A"]["lyrics"], "あいうえ")
        self.assertEqual(out["sections"]["B"]["melody"], "G4:4 | C5:4")
        self.assertEqual(out["tempo"], 120)

    def test_same_change_on_both_sides_is_not_a_conflict(self):
        both = mk(A_lyrics="おなじ")
        plan = merge.analyze(mk(), both, both)
        self.assertEqual(plan["units"], [])

    def test_conflict_reports_fields(self):
        cur, prop = mk(A_lyrics="じぶん", A_melody="C4:4 | E4:4"), mk(A_lyrics="ていあん")
        plan = merge.analyze(mk(), cur, prop)
        self.assertEqual(plan["conflicts"], ["section:A"])
        fields = {f["field"]: f for f in plan["units"][0]["fields"]}
        self.assertEqual(fields["lyrics"], {"field": "lyrics", "base": "あい / うえ", "mine": "じぶん", "theirs": "ていあん"})
        self.assertEqual(fields["melody"]["theirs"], BASE["sections"]["A"]["melody"])  # 提案は melody を変えていない

    def test_meta_conflicts_are_per_key(self):
        cur, prop = mk(tempo=90, style="rock"), mk(tempo=140)
        plan = merge.analyze(mk(), cur, prop)
        dec = {u["id"]: u["decision"] for u in plan["units"]}
        self.assertEqual(dec, {"meta:tempo": "conflict", "meta:style": "mine"})
        self.assertEqual(plan["units"][0]["label"], "テンポ")


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.cur, self.prop = mk(A_lyrics="じぶん", tempo=90), mk(A_lyrics="ていあん", tempo=140, B_lyrics="さし / すせ")

    def test_unresolved_conflict_is_error(self):
        with self.assertRaises(MergeError) as cm:
            merge.resolve(mk(), self.cur, self.prop, {"section:A": "theirs"})
        self.assertIn("テンポ", str(cm.exception))
        with self.assertRaises(MergeError):
            merge.resolve(mk(), self.cur, self.prop, None)

    def test_choices_are_applied(self):
        out = load(merge.resolve(mk(), self.cur, self.prop, {"section:A": "mine", "meta:tempo": "theirs"}))
        self.assertEqual((out["sections"]["A"]["lyrics"], out["tempo"]), ("じぶん", 140))
        self.assertEqual(out["sections"]["B"]["lyrics"], "さし / すせ")  # 衝突していない B は提案を自動で取り込む
        out = load(merge.resolve(mk(), self.cur, self.prop, {"section:A": "theirs", "meta:tempo": "mine"}))
        self.assertEqual((out["sections"]["A"]["lyrics"], out["tempo"]), ("ていあん", 90))

    def test_bad_choice_value(self):
        with self.assertRaises(MergeError):
            merge.resolve(mk(), self.cur, self.prop, {"section:A": "both", "meta:tempo": "mine"})

    def test_section_deleted_vs_modified_is_conflict(self):
        base = BASE
        cur = copy.deepcopy(base); cur["sections"]["B"]["lyrics"] = "かえた / けこ"
        prop = copy.deepcopy(base); del prop["sections"]["B"]; prop["structure"] = ["A"]
        plan = merge.analyze(dump_yaml(base), dump_yaml(cur), dump_yaml(prop))
        self.assertIn("section:B", plan["conflicts"])
        kept = load(merge.resolve(dump_yaml(base), dump_yaml(cur), dump_yaml(prop),
                                  {"section:B": "mine", "meta:structure": "mine"}))
        self.assertIn("B", kept["sections"])
        gone = load(merge.resolve(dump_yaml(base), dump_yaml(cur), dump_yaml(prop),
                                  {"section:B": "theirs", "meta:structure": "theirs"}))
        self.assertNotIn("B", gone["sections"])

    def test_added_sections_from_both_sides(self):
        cur = copy.deepcopy(BASE); cur["sections"]["C"] = {"chords": "F"}
        prop = copy.deepcopy(BASE); prop["sections"]["D"] = {"chords": "G"}
        out = load(merge.resolve(mk(), dump_yaml(cur), dump_yaml(prop), None))
        self.assertEqual(list(out["sections"]), ["A", "B", "C", "D"])

    def test_merged_result_that_cannot_be_a_song_is_rejected(self):
        # 提案が B を消し、自分が structure に B を足していたら、合成すると structure が存在しない B を指す
        cur = copy.deepcopy(BASE); cur["structure"] = ["A", "B", "B"]
        prop = copy.deepcopy(BASE); del prop["sections"]["B"]; prop["structure"] = ["A"]
        with self.assertRaises(MergeError) as cm:
            merge.resolve(mk(), dump_yaml(cur), dump_yaml(prop), {"section:B": "theirs", "meta:structure": "mine"})
        self.assertIn("曲として読めません", str(cm.exception))
        bad_schema = copy.deepcopy(BASE); bad_schema["style"] = "jazz"
        with self.assertRaises(MergeError) as cm:
            merge.resolve(mk(), mk(), dump_yaml(bad_schema), None)
        self.assertIn("style", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
