import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from musicai import migrate, service
from musicai.migrate import ensure_version, file_version, migrate_file, migrate_text
from musicai.schema import validate_data

OLD = "# 説明コメント\n\ntitle: x\nkey: C major\nsections:\n  A:\n    chords: C   # 行末コメント\n"


class MigrateTest(unittest.TestCase):
    def test_adds_version_keeps_comments(self):
        new, a, b = migrate_text(OLD)
        self.assertEqual((a, b), (0, 1))
        self.assertTrue(new.startswith("# 説明コメント\n\nschema_version: 1\ntitle: x"))
        self.assertIn("# 行末コメント", new)
        self.assertEqual(file_version(new), 1)

    def test_idempotent(self):
        new, _, _ = migrate_text(OLD)
        again, a, b = migrate_text(new)
        self.assertEqual((again, a, b), (new, 1, 1))

    def test_crlf_kept(self):
        new, _, _ = migrate_text(OLD.replace("\n", "\r\n"))
        self.assertIn("schema_version: 1\r\n", new)

    def test_errors(self):
        with self.assertRaises(ValueError):
            migrate_text("- a\n")
        with self.assertRaises(ValueError):
            migrate_text("schema_version: abc\n")
        with self.assertRaises(ValueError):
            migrate_text("schema_version: -1\n")
        with self.assertRaises(ValueError):
            migrate_text("schema_version: 99\nsections: {}\n")

    def test_chain_of_migrations(self):
        # 将来 v2 を足したときの構造を確認（変換関数を連ねて新しいバージョンまで進む）
        def v1_to_v2(text):
            return text.replace("schema_version: 1", "schema_version: 2")

        with mock.patch.object(migrate, "CURRENT_VERSION", 2), \
                mock.patch.dict(migrate.MIGRATIONS, {1: v1_to_v2}):
            new, a, b = migrate_text(OLD)
            self.assertEqual((a, b), (0, 2))
            self.assertIn("schema_version: 2", new)

    def test_migrate_file_and_dry_run(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.yaml"
            p.write_text(OLD, encoding="utf-8")
            self.assertEqual(migrate_file(p, dry_run=True), (0, 1))
            self.assertEqual(p.read_text(encoding="utf-8"), OLD)
            self.assertEqual(migrate_file(p), (0, 1))
            self.assertEqual(file_version(p.read_text(encoding="utf-8")), 1)
            self.assertEqual(migrate_file(p), (1, 1))

    def test_ensure_version(self):
        self.assertEqual(list(ensure_version({"a": 1})), ["schema_version", "a"])
        self.assertEqual(ensure_version({"schema_version": 3})["schema_version"], 3)


class SaveSongTextTest(unittest.TestCase):
    def test_save_migrates_and_validates(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(service, "SONGS_DIR", Path(d)):
            p = service.save_song_text("テスト", OLD)
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], 1)
            self.assertIn("# 行末コメント", p.read_text(encoding="utf-8"))
            self.assertTrue(validate_data(data).ok)
            with self.assertRaises(ValueError) as cm:
                service.save_song_text("bad", OLD + "  B:\n    melodyy: x\n")
            self.assertIn("sections.B.melodyy", str(cm.exception))
            with self.assertRaises(ValueError):
                service.save_song_text("bad2", "- 1\n")
            self.assertFalse((Path(d) / "bad.yaml").exists())


if __name__ == "__main__":
    unittest.main()
