import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from musicai import service

ROOT = Path(__file__).resolve().parent.parent


class MusicaiHomeTest(unittest.TestCase):
    def run_py(self, code, **env):
        e = {k: v for k, v in os.environ.items() if k != "MUSICAI_HOME"}
        e.update(env)
        return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=e, capture_output=True, text=True, timeout=60)

    def test_env_var_changes_data_dir(self):
        code = "from musicai import service; print(service.DATA_DIR, service.SONGS_DIR, service.OUTPUT_DIR)"
        with tempfile.TemporaryDirectory() as d:
            out = self.run_py(code, MUSICAI_HOME=d).stdout.split()
            home = str(Path(d).resolve())
            # 区切り文字は OS ごとに違う（Windows は \）ので Path で組み立てて比べる
            self.assertEqual(out, [home, str(Path(home) / "songs"), str(Path(home) / "output")])
        default = self.run_py(code).stdout.split()
        self.assertEqual(default[0], str(ROOT))  # 指定しなければ、今までどおりソースのフォルダ

    def test_first_run_copies_sample_songs_and_they_are_writable(self):
        with tempfile.TemporaryDirectory() as d:
            res, data = Path(d) / "res", Path(d) / "data"
            (res / "songs").mkdir(parents=True)
            sample = res / "songs" / "a.yaml"
            sample.write_text("x: 1\n", encoding="utf-8")
            sample.chmod(0o444)  # Nix のストアのように読み取り専用
            with mock.patch.multiple(service, RESOURCE_DIR=res, DATA_DIR=data, SONGS_DIR=data / "songs",
                                     OUTPUT_DIR=data / "output"):
                service.ensure_data_dirs()
                copied = data / "songs" / "a.yaml"
                self.assertEqual(copied.read_text(encoding="utf-8"), "x: 1\n")
                self.assertTrue(os.access(copied, os.W_OK))  # コピーは上書き保存できる
                copied.write_text("x: 2\n", encoding="utf-8")
                service.ensure_data_dirs()  # 2 回目は、保存済みの曲を上書きしない
                self.assertEqual(copied.read_text(encoding="utf-8"), "x: 2\n")
            sample.chmod(0o644)

    def test_no_copy_when_data_dir_is_the_source(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "songs").mkdir()
            (base / "songs" / "keep.yaml").write_text("x: 1\n", encoding="utf-8")
            (base / "empty").mkdir()
            with mock.patch.multiple(service, RESOURCE_DIR=base, DATA_DIR=base, SONGS_DIR=base / "songs",
                                     OUTPUT_DIR=base / "output"):
                service.ensure_data_dirs()
            self.assertEqual([p.name for p in (base / "songs").iterdir()], ["keep.yaml"])
            # ソースのフォルダで動かすとき（開発）は、何もコピーしない
            with mock.patch.multiple(service, RESOURCE_DIR=base, DATA_DIR=base, SONGS_DIR=base / "empty",
                                     OUTPUT_DIR=base / "output"):
                service.ensure_data_dirs()
            self.assertEqual(list((base / "empty").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
