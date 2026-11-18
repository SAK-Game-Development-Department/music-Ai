import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from musicai import app, service
from tests.test_history import SONG_V1, SONG_V2, git


class HistoryApiTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        git(root, "init", "-q")
        songs = root / "songs"
        songs.mkdir()
        self.songs = songs
        (songs / "s.yaml").write_text(SONG_V1, encoding="utf-8")
        self._p = mock.patch.object(service, "SONGS_DIR", songs)
        self._p.start()
        self._e = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull})
        self._e.start()
        for k in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
            os.environ.pop(k, None)

    def tearDown(self):
        self._e.stop(); self._p.stop(); self._td.cleanup()

    def test_flow(self):
        self.assertEqual(app.api_history_status({}, {}), {"available": True, "message": ""})
        r1 = app.api_version_save({}, {"name": "s", "note": "1回目"})
        self.assertTrue(r1["saved"])
        (self.songs / "s.yaml").write_text(SONG_V2, encoding="utf-8")
        app.api_version_save({}, {"name": "s"})
        h = app.api_history({"name": ["s"]}, {})
        self.assertEqual([v["no"] for v in h["versions"]], [1, 2])
        d = app.api_history_diff({"name": ["s"], "a": ["1"], "b": ["2"]}, {})
        self.assertTrue(any(s["changed"] for s in d["sections"]))
        blob = json.dumps([r1, h, d], ensure_ascii=False)
        self.assertNotRegex(blob, r"[0-9a-f]{7,40}")
        for w in ("commit", "branch", "hash"):
            self.assertNotIn(w, blob.lower())

    def test_bad_input_is_value_error(self):
        app.api_version_save({}, {"name": "s"})
        with self.assertRaises(ValueError):
            app.api_history_diff({"name": ["s"], "a": ["x"], "b": ["1"]}, {})
        with self.assertRaises(ValueError):
            app.api_history_diff({"name": ["s"], "a": ["1"], "b": ["9"]}, {})

    def test_unavailable_returns_message_not_error(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(service, "SONGS_DIR", Path(d)), \
                mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": d}):
            msg = {"available": False, "message": "履歴機能は使えません"}
            self.assertEqual(app.api_history_status({}, {}), msg)
            self.assertEqual(app.api_history({"name": ["s"]}, {}), msg)
            self.assertEqual(app.api_history_diff({"name": ["s"], "a": ["1"], "b": ["2"]}, {}), msg)
            self.assertEqual(app.api_version_save({}, {"name": "s"}), msg)
            self.assertNotIn("error", app.api_history({"name": ["s"]}, {}))


if __name__ == "__main__":
    unittest.main()
