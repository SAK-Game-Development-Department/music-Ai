"""musicai アプリ: ブラウザで操作する作曲・替え歌ソフト。

起動: start_windows.bat / start_mac.command をダブルクリック、または python -m musicai app
外部ライブラリ不要（Python 標準の http.server）。このパソコンの中だけで動く（127.0.0.1）。
"""
from __future__ import annotations

import json
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

WEB_DIR = Path(__file__).resolve().parent / "web"
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
}


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
        if path.startswith("/output/"):
            return self._file(service.OUTPUT_DIR, unquote(path[len("/output/"):]), download="dl" in url.query)
        if path == "/":
            path = "/index.html"
        return self._file(WEB_DIR, unquote(path.lstrip("/")))

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
        self._send(200, p.read_bytes(), ctype, extra)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


def run(port: int = 8765, open_browser: bool = True):
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
