"""musicai アプリ: ブラウザで操作する作曲・替え歌ソフト。

起動: start_windows.bat / start_mac.command をダブルクリック、または python -m musicai app
外部ライブラリ不要（Python 標準の http.server）。このパソコンの中だけで動く（127.0.0.1）。
"""
from __future__ import annotations

import json
import re
import mimetypes
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import yaml

from . import history, service
from .composer import compose
from .lyrics import phrases, split_mora
from .song import song_from_dict
from .theory import PROGRESSIONS, parse_key, progression_to_chords

WEB_DIR = service.RESOURCE_DIR / "musicai" / "web" if service.FROZEN else Path(__file__).resolve().parent / "web"
_render_lock = threading.Lock()


def _load_yaml_text(text: str) -> dict:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("曲データの形式が正しくありません")
    return data


def api_songs(_q, _b):
    out = []
    for p in sorted(service.SONGS_DIR.glob("*.yaml"), key=lambda p: -p.stat().st_mtime):
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict) or "sections" not in data:
                continue
            title = data.get("title", p.stem)
        except Exception:
            title = p.stem
        out.append({"name": p.stem, "title": title})
    return {"songs": out}


def api_song(q, _b):
    name = service.safe_name(q.get("name", [""])[0])
    p = service.SONGS_DIR / f"{name}.yaml"
    if not p.exists():
        raise ValueError(f"曲が見つかりません: {name}")
    text = p.read_text(encoding="utf-8")
    view = service.song_view(song_from_dict(_load_yaml_text(text)))
    return {"name": name, "yaml": text, "view": view}


def api_check(_q, b):
    data = _load_yaml_text(b["yaml"])
    return {"view": service.song_view(song_from_dict(data))}


def api_save(_q, b):
    data = _load_yaml_text(b["yaml"])
    song_from_dict(data)  # 検証
    p = service.save_song_text(b.get("name") or data.get("title", "untitled"), b["yaml"])
    return {"name": p.stem}


def api_delete(_q, b):
    p = service.SONGS_DIR / f"{service.safe_name(b['name'])}.yaml"
    if p.exists():
        p.unlink()
    return {"ok": True}


def _history() -> history.History:
    return history.History(service.SONGS_DIR)


def _unavailable() -> dict:
    return {"available": False, "message": history.UNAVAILABLE_MESSAGE}


def api_history_status(_q, _b):
    return _history().status()


def api_history(q, _b):
    name = service.safe_name(q.get("name", [""])[0])
    try:
        versions = _history().list_versions(name)
    except history.HistoryUnavailable:
        return _unavailable()
    return {"available": True, "name": name, "versions": [v.to_dict() for v in versions]}


def api_history_diff(q, _b):
    name = service.safe_name(q.get("name", [""])[0])
    try:
        d = _history().lyrics_diff(name, int(q.get("a", [""])[0]), int(q.get("b", [""])[0]))
    except history.HistoryUnavailable:
        return _unavailable()
    return {"available": True, "name": name, **d}


def api_version_save(_q, b):
    name = service.safe_name(b.get("name", ""))
    try:
        r = _history().save_version(name, b.get("note", ""))
    except history.HistoryUnavailable:
        return _unavailable()
    return {"available": True, "name": name, **r}


def api_render(_q, b):
    data = _load_yaml_text(b["yaml"])
    song = song_from_dict(data)
    stem = service.safe_name(b.get("name") or song.title)
    mute = set(b.get("mute") or [])
    if mute:
        stem += "_" + "_".join(sorted(mute)) + "なし"
    with _render_lock:
        files = service.render_song(song, stem, mute)
    return {"files": files, "view": service.song_view(song)}


def api_compose(_q, b):
    spec = b["spec"]
    data = compose(spec)
    song = song_from_dict(data)
    text = service.dump_yaml(data)
    name = None
    if b.get("save", True):
        name = service.save_song_text(b.get("name") or data["title"], text).stem
    return {"name": name, "yaml": text, "view": service.song_view(song)}


def api_kaeuta(_q, b):
    data = _load_yaml_text(b["yaml"])
    new, report = service.kaeuta(data, b["lyrics"], b.get("title"))
    song = song_from_dict(new)
    text = service.dump_yaml(new)
    name = service.save_song_text(b.get("name") or new["title"], text).stem
    return {"name": name, "yaml": text, "report": report, "view": service.song_view(song)}


def api_mora(_q, b):
    try:
        syls = split_mora(b.get("text", ""))
    except ValueError as e:
        return {"error": str(e), "phrases": []}
    return {"phrases": [[s.text for s in p] for p in phrases(syls)]}


def api_progressions(q, _b):
    key = parse_key(q.get("key", ["C major"])[0])
    return {"key": key.name(), "items": [
        {"name": n, "degrees": d, "desc": desc, "chords": progression_to_chords(n, key)}
        for n, (d, desc) in PROGRESSIONS.items()]}


def api_chords(_q, b):
    key = parse_key(b.get("key", "C major"))
    return {"chords": progression_to_chords(b.get("progression", ""), key)}


# ---------------- 取り込み（時間がかかるのでバックグラウンドで実行） ----------------
JOBS: dict[str, dict] = {}


def _run_import(job_id: str, source: str, start, end, title):
    job = JOBS[job_id]

    def progress(msg):
        job["message"] = msg

    try:
        with _render_lock:
            job["result"] = service.import_song(source, start, end, title, progress)
        job["state"] = "done"
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        job["state"] = "error"
        job["error"] = str(e)


def _parse_time(v):
    """'1:23' / '83' / '' → 秒（None 可）。"""
    if v in (None, ""):
        return None
    t = str(v).strip()
    if ":" in t:
        parts = [float(x) for x in t.split(":")]
        sec = 0.0
        for x in parts:
            sec = sec * 60 + x
        return sec
    return float(t)


def api_import(_q, b):
    import uuid

    source = (b.get("url") or b.get("upload") or "").strip()
    if not source:
        raise ValueError("YouTube の URL か音声ファイルを指定してください")
    if b.get("upload"):
        p = (service.IMPORTS_DIR / "uploads" / Path(source).name).resolve()
        if not p.is_file():
            raise ValueError("アップロードしたファイルが見つかりません")
        source = str(p)
    start = _parse_time(b.get("start")) or 0.0
    end = _parse_time(b.get("end"))
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"state": "running", "message": "準備しています…"}
    threading.Thread(target=_run_import, args=(job_id, source, start, end, b.get("title")), daemon=True).start()
    return {"job": job_id}


def api_job(q, _b):
    job = JOBS.get(q.get("id", [""])[0])
    if not job:
        raise ValueError("ジョブが見つかりません")
    return job


def api_import_info(_q, _b):
    from .transcribe import demucs_available

    try:
        import yt_dlp  # noqa: F401
        ytdlp = True
    except ImportError:
        ytdlp = not service.FROZEN  # ソース版は必要になったとき自動でインストールする
    return {"ytdlp": ytdlp, "demucs": demucs_available()}


ROUTES = {
    ("GET", "/api/songs"): api_songs,
    ("GET", "/api/song"): api_song,
    ("GET", "/api/progressions"): api_progressions,
    ("POST", "/api/check"): api_check,
    ("POST", "/api/save"): api_save,
    ("POST", "/api/delete"): api_delete,
    ("GET", "/api/history/status"): api_history_status,
    ("GET", "/api/history"): api_history,
    ("GET", "/api/history/diff"): api_history_diff,
    ("POST", "/api/version/save"): api_version_save,
    ("POST", "/api/render"): api_render,
    ("POST", "/api/compose"): api_compose,
    ("POST", "/api/kaeuta"): api_kaeuta,
    ("POST", "/api/mora"): api_mora,
    ("POST", "/api/chords"): api_chords,
    ("POST", "/api/import"): api_import,
    ("GET", "/api/job"): api_job,
    ("GET", "/api/import_info"): api_import_info,
}

MAX_UPLOAD = 300 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 静かに
        pass

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _handle(self, method: str):
        url = urlparse(self.path)
        path = url.path
        if method == "POST" and path == "/api/upload":
            return self._upload()
        fn = ROUTES.get((method, path))
        if fn:
            try:
                body = {}
                if method == "POST":
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(n) or b"{}")
                self._json(200, fn(parse_qs(url.query), body))
            except (ValueError, KeyError, yaml.YAMLError) as e:
                self._json(400, {"error": str(e)})
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                self._json(500, {"error": f"内部エラー: {e}"})
            return
        if method != "GET":
            return self._json(404, {"error": "not found"})
        if path.startswith("/data/imports/"):
            return self._file(service.IMPORTS_DIR, unquote(path[len("/data/imports/"):]))
        if path.startswith("/output/"):
            return self._file(service.OUTPUT_DIR, unquote(path[len("/output/"):]), download="dl" in url.query)
        if path == "/":
            path = "/index.html"
        return self._file(WEB_DIR, unquote(path.lstrip("/")))

    def _upload(self):
        """音声ファイルを受け取って imports/uploads/ に保存。本文 = ファイルそのもの、X-Filename に名前。"""
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_UPLOAD:
                raise ValueError("ファイルが大きすぎるか空です（300MB まで）")
            name = unquote(self.headers.get("X-Filename") or "upload")
            name = service.safe_name(Path(name).stem)[:60] + (Path(name).suffix.lower()[:6] or ".bin")
            d = service.IMPORTS_DIR / "uploads"
            d.mkdir(parents=True, exist_ok=True)
            p = d / name
            remaining = n
            with open(p, "wb") as f:
                while remaining:
                    chunk = self.rfile.read(min(remaining, 1 << 20))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
            self._json(200, {"upload": p.name})
        except ValueError as e:
            self._json(400, {"error": str(e)})

    def _file(self, base: Path, rel: str, download=False):
        p = (base / rel).resolve()
        if base.resolve() not in p.parents or not p.is_file():
            return self._json(404, {"error": "not found"})
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if p.suffix == ".musicxml":
            ctype = "application/vnd.recordare.musicxml+xml"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        extra = {}
        if download:
            from urllib.parse import quote
            extra["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(p.name)}"
        data = p.read_bytes()
        extra["Accept-Ranges"] = "bytes"
        rng = self.headers.get("Range", "")
        m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
        if m and (m.group(1) or m.group(2)):
            size = len(data)
            if m.group(1):
                a = int(m.group(1))
                b = int(m.group(2)) if m.group(2) else size - 1
            else:
                a, b = max(0, size - int(m.group(2))), size - 1
            b = min(b, size - 1)
            if a > b:
                return self._send(416, b"", ctype, {"Content-Range": f"bytes */{size}"})
            extra["Content-Range"] = f"bytes {a}-{b}/{size}"
            return self._send(206, data[a:b + 1], ctype, extra)
        self._send(200, data, ctype, extra)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


def run(port: int = 8765, open_browser: bool = True):
    service.ensure_data_dirs()
    server = None
    for p in range(port, port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit("ポートが使えません")
    url = f"http://127.0.0.1:{port}/"
    print("=" * 50)
    print(" 🎵 music-Ai を起動しました")
    print(f"   ブラウザで開く: {url}")
    print(f"   曲の保存先: {service.SONGS_DIR}")
    print("   終了するにはこのウィンドウを閉じるか Ctrl+C")
    print("=" * 50)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了しました")


if __name__ == "__main__":
    run()
