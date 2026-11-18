import unittest
from fractions import Fraction as F

from musicai.composer import compose
from musicai.kaeuta import fit_lyrics
from musicai.lyrics import LyricError, count_mora, split_mora
from musicai.song import load_song, parse_melody, song_from_dict
from musicai.theory import parse_key, parse_pitch, progression_to_chords


class TheoryTest(unittest.TestCase):
    def test_pitch(self):
        self.assertEqual(parse_pitch("C4"), 60)
        self.assertEqual(parse_pitch("A4"), 69)
        self.assertEqual(parse_pitch("Bb3"), 58)

    def test_progressions(self):
        self.assertEqual(progression_to_chords("王道進行", parse_key("C major")), ["F", "G", "Em", "Am"])
        self.assertEqual(progression_to_chords("I V vi IV", parse_key("G")), ["G", "D", "Em", "C"])
        self.assertEqual(progression_to_chords("IVmaj7 III7 vi7", parse_key("C")), ["Fmaj7", "E7", "Am7"])
        # マイナーキーで進行名 → 平行調基準
        self.assertEqual(progression_to_chords("小室進行", parse_key("A minor")), ["Am", "F", "G", "C"])


class LyricsTest(unittest.TestCase):
    def test_mora(self):
        self.assertEqual([s.text for s in split_mora("きょうはがっこう")], ["きょ", "う", "は", "が", "っ", "こ", "う"])
        self.assertEqual(count_mora("ラーメン"), 4)
        self.assertEqual(count_mora("{空|そら}へ"), 3)
        self.assertEqual([s.text for s in split_mora("twin-kle star")], ["twin", "kle", "star"])

    def test_phrases_and_kanji(self):
        syl = split_mora("あい / うえお\nか")
        self.assertEqual([s.phrase for s in syl], [0, 0, 1, 1, 1, 2])
        with self.assertRaises(LyricError):
            split_mora("空")

    def test_vowel(self):
        self.assertEqual([s.vowel for s in split_mora("きょうん")], ["o", "u", "n"])


class KaeutaTest(unittest.TestCase):
    MEL = "C4:1 C4 G4 G4 | A4 A4 G4:2 | F4:1 F4 E4 E4 | D4 D4 C4:2"

    def _sung(self, notes):
        return [n for n in notes if not n.is_rest and not n.melisma]

    def test_more_mora_splits(self):
        notes, _ = parse_melody(self.MEL, 4)
        out, rep = fit_lyrics(notes, "らーめんたべたい / ちゃーしゅーおおめで")
        self.assertEqual(len(self._sung(out)), 16)
        self.assertEqual(sum((n.dur for n in out), F(0)), 16)

    def test_fewer_mora_ties_or_melisma(self):
        notes, _ = parse_melody(self.MEL, 4)
        out, _ = fit_lyrics(notes, "あいう / えお")
        self.assertEqual(len(self._sung(out)), 5)
        self.assertEqual(sum((n.dur for n in out), F(0)), 16)


class SongTest(unittest.TestCase):
    def test_example_songs_load_clean(self):
        for f in ["songs/hoshi.yaml", "songs/hajimari.yaml"]:
            song = load_song(f)
            self.assertEqual([w for s in song.sections.values() for w in s.warnings], [], f)

    def test_compose_fits_lyrics(self):
        spec = {"key": "D major", "tempo": 110, "seed": 1, "structure": ["v", "c"],
                "sections": {"v": {"progression": "カノン進行", "lyrics": "あいうえおかきくけこ / さしすせそ"},
                             "c": {"progression": "王道進行", "energy": "high",
                                   "lyrics": "たちつてと / なにぬねの / はひふへほまみむめも"}}}
        song = song_from_dict(compose(spec))
        for sec in song.sections.values():
            self.assertEqual(sec.warnings, [])
            self.assertEqual(sec.length % 4, 0)
        # フレーズ末の音はその時のコードの構成音
        from musicai.theory import parse_chord
        sec = song.sections["c"]
        t = F(0)
        for i, n in enumerate(sec.notes):
            nxt_rest = i + 1 == len(sec.notes) or sec.notes[i + 1].is_rest
            if not n.is_rest and nxt_rest:
                ch = next(c for s, d, c in sec.chords if s <= t < s + d)
                self.assertIn(n.pitch % 12, parse_chord(ch).pcs)
            t += n.dur


if __name__ == "__main__":
    unittest.main()


class TranscribeTest(unittest.TestCase):
    """自作曲を音にして聴き取り、正解と比べる（音源取り込みの精度の下限チェック）。"""

    @classmethod
    def setUpClass(cls):
        import tempfile

        from musicai.arrange import arrange
        from musicai.audio_io import AudioError, ffmpeg_exe
        from musicai.synth import render, write_wav

        try:
            ffmpeg_exe()
        except AudioError:
            raise unittest.SkipTest("ffmpeg が無い環境では音声取り込みのテストを飛ばす")

        cls.tmp = tempfile.TemporaryDirectory()
        cls.song = load_song("songs/hoshi.yaml")
        cls.wav = f"{cls.tmp.name}/hoshi.wav"
        write_wav(render(arrange(cls.song), cls.song.tempo), cls.wav)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_tempo_key_chords_melody(self):
        from musicai.transcribe import analyze

        an = analyze(self.wav)
        self.assertAlmostEqual(an.tempo, 96, delta=0.5)
        self.assertEqual(an.key.name(), "C major")
        flat = [c for bar in an.chords for c in bar.split()]
        self.assertGreaterEqual(sum(c in ("C", "F", "G") for c in flat) / len(flat), 0.8)
        # 音符の中央の時刻で、正解の音高と一致する割合
        spb = 60 / an.tempo
        truth = []
        for st, sec in self.song.timeline():
            t = float(st) * 60 / self.song.tempo
            for n in sec.notes:
                d = float(n.dur) * 60 / self.song.tempo
                if not n.is_rest:
                    truth.append((t, t + d, n.pitch))
                t += d
        ok = 0
        for a, d, p in an.notes:
            mid = an.t0 + (a + d / 2) * spb / 4
            ok += any(s <= mid < e and p == tp for s, e, tp in truth)
        self.assertGreaterEqual(ok / len(an.notes), 0.6)

    def test_import_and_kaeuta(self):
        from pathlib import Path

        from musicai import service

        old = service.DATA_DIR, service.SONGS_DIR, service.IMPORTS_DIR, service.OUTPUT_DIR
        base = Path(self.tmp.name)
        service.DATA_DIR, service.SONGS_DIR, service.IMPORTS_DIR, service.OUTPUT_DIR = (
            base, base / "songs", base / "imports", base / "output")
        try:
            res = service.import_song(self.wav, 9, 40, "取り込み")
            song = load_song(base / "songs" / f"{res['name']}.yaml")
            self.assertTrue(service.source_info(song))
            data = song.raw
            new, report = service.kaeuta(data, {"パート1": "らーめん / たべたい"})
            files = service.render_song(song_from_dict(new), "k")
            self.assertTrue((base / "output" / files["wav"]).stat().st_size > 100000)
        finally:
            service.DATA_DIR, service.SONGS_DIR, service.IMPORTS_DIR, service.OUTPUT_DIR = old


class LyricGenTest(unittest.TestCase):
    """歌詞の自動生成: どんな数でもモーラ数ぴったり / ストーリーは起→結へ進む / 替え歌に使える。"""

    def test_exact_mora_for_any_count(self):
        from musicai.lyricgen import THEMES, generate

        counts = list(range(1, 31))
        for story in (True, False):
            for th in THEMES + [None]:
                for seed in range(3):
                    lyr, _ = generate([("A", counts)], story=story, theme=th, seed=seed)
                    got = [len(split_mora(line)) for line in lyr["A"].split("\n")]
                    self.assertEqual(got, counts, (story, th, seed))

    def test_story_moves_from_start_to_end(self):
        from musicai.lyricgen import BANK, GENERIC, generate

        lyr, theme = generate([("A", [7] * 4), ("B", [7] * 4), ("C", [7] * 4), ("D", [7] * 4)],
                              story=True, theme="恋", seed=1)
        self.assertEqual(theme, "恋")
        start = set(BANK["恋"]["起"] + GENERIC["起"])
        end = set(BANK["恋"]["結"] + GENERIC["結"])
        first, last = lyr["A"], lyr["D"]
        self.assertTrue(any(w in first for w in start), first)
        self.assertTrue(any(w in last for w in end), last)

    def test_auto_kaeuta_fits_without_adjustment(self):
        from musicai import service

        data = load_song("songs/hoshi.yaml").raw
        lyrics, _ = service.auto_lyrics(data, story=True, theme="夏", seed=2)
        self.assertEqual(set(lyrics), {"A", "B", "A2"})
        new, report = service.kaeuta(data, lyrics)
        self.assertFalse([r for r in report if "△" in r or "⚠" in r], report)
        song = song_from_dict(new)
        self.assertEqual([w for s in song.sections.values() for w in s.warnings], [])

    def test_keep_user_lyrics(self):
        from musicai import service

        data = load_song("songs/hoshi.yaml").raw
        lyrics, _ = service.auto_lyrics(data, keep={"B": "じぶんでかいた / かしだよ"}, seed=1)
        self.assertEqual(lyrics["B"], "じぶんでかいた / かしだよ")
        self.assertIn("A", lyrics)


class LyricQualityTest(unittest.TestCase):
    """歌詞の言い回し: 行が途中で切れない / 原曲のくり返しをまねる / 歌わないパートには付けない。"""

    def test_lines_do_not_end_mid_sentence(self):
        from musicai.lyricgen import LEAD_ENDINGS, THEMES, generate

        counts = [5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
        for th in THEMES:
            for seed in range(4):
                lyr, _ = generate([("A", counts)], story=bool(seed % 2), theme=th, seed=seed)
                for line in lyr["A"].split("\n"):
                    last = line.split(" ")[-1]
                    # 行末の「よ・ね・だよ・かな」は合いの手。それを除いた最後の言葉が「つなぎ」で終わらない
                    for tail in ("だよ", "かな", "よ", "ね"):
                        if last.endswith(tail) and len(last) > len(tail) + 2:
                            last = last[: -len(tail)]
                            break
                    self.assertFalse(last.endswith(("を", "が", "は", "けど", "から", "のに")), (th, line))

    def test_repeats_where_original_repeats(self):
        from musicai.lyricgen import generate

        orig = {"A": ["よぞらにひかる", "ちいさなほしよ"], "B": ["とおくのまちを", "てらしているよ"],
                "C": ["よぞらにひかる", "ちいさなほしよ"]}
        lyr, _ = generate([("A", [7, 7]), ("B", [7, 7]), ("C", [7, 7])], seed=1, originals=orig)
        self.assertEqual(lyr["A"], lyr["C"])
        self.assertNotEqual(lyr["A"], lyr["B"])

    def test_unsung_parts_get_no_lyrics(self):
        from musicai import service

        data = load_song("songs/hoshi.yaml").raw
        off = service.apply_sing(data, {"B": False})
        lyrics, _ = service.auto_lyrics(off, seed=1)
        self.assertNotIn("B", lyrics)
        new, _ = service.kaeuta(off, {**lyrics, "B": "うたわない / はずのぱーと"})
        song = song_from_dict(new)
        self.assertFalse(song.sections["B"].sing)
        self.assertEqual(song.sections["B"].lyrics_text, "とおくのまちを / てらしているよ")  # 元のまま
        from musicai.arrange import arrange
        arr = arrange(song)
        b_start = next(float(t) for t, s in song.timeline() if s.name == "B")
        b_end = b_start + float(song.sections["B"].length)
        self.assertFalse([e for e in arr.tracks["vocal"] if b_start <= e.start < b_end])


class VocalDetectionTest(unittest.TestCase):
    """取り込み: イントロ・間奏・アウトロ（歌っていない小節）を見分けて、歌わないパートにする。"""

    def test_intro_interlude_outro_are_not_sung(self):
        import tempfile

        from musicai.arrange import arrange
        from musicai.synth import render, write_wav
        from musicai.transcribe import analysis_to_song, analyze

        song = load_song("songs/hajimari.yaml")  # イントロ 4 / 間奏 4 / アウトロ 4 小節
        with tempfile.TemporaryDirectory() as d:
            wav = f"{d}/h.wav"
            write_wav(render(arrange(song), song.tempo), wav)
            an = analyze(wav)
        data = analysis_to_song(an, "t")
        names = list(data["sections"])
        self.assertEqual(names[0], "イントロ")
        self.assertEqual(names[-1], "アウトロ")
        self.assertTrue(any(n.startswith("間奏") for n in names), names)
        for n, sec in data["sections"].items():
            self.assertEqual(sec.get("sing", True), not (n.startswith(("イントロ", "間奏", "アウトロ"))), n)
        # 歌っている小節のうち、歌と判定できた割合
        sung_bars = sum(len(s["chords"].split("|")) for s in data["sections"].values() if s.get("sing", True))
        self.assertGreaterEqual(sung_bars, 36)  # 正解は 40 小節
