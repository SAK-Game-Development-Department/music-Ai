"""exe / アプリの入口: ダブルクリックでアプリ（ブラウザ画面）を起動する。

  --selftest  サンプル曲を 1 つ書き出して終了（ビルド確認用）
"""
import sys
import traceback


def selftest() -> int:
    from musicai import service
    from musicai.song import load_song

    service.ensure_data_dirs()
    song = load_song(service.RESOURCE_DIR / "songs" / "hoshi.yaml")
    files = service.render_song(song, "selftest")
    for key in ("midi", "musicxml", "lyrics", "wav"):
        p = service.OUTPUT_DIR / files[key]
        assert p.is_file() and p.stat().st_size > 0, f"{key} が作れませんでした"
    # 取り込み（ffmpeg でのデコード → 聴き取り → カラオケ化）も確認
    res = service.import_song(str(service.OUTPUT_DIR / files["wav"]), 9, 40, "selftest_import")
    imported = load_song(service.SONGS_DIR / f"{res['name']}.yaml")
    assert sum(1 for s in imported.sections.values() for n in s.notes if not n.is_rest) > 10, "聴き取りに失敗"
    (service.SONGS_DIR / f"{res['name']}.yaml").unlink()
    import yt_dlp  # noqa: F401  同梱されているか
    from musicai.reading import to_ruby

    assert to_ruby("夜空に光る") == "{夜空|よぞら}に{光|ひか}る", "漢字の読みが使えません"
    # Whisper（同梱されていれば）。MUSICAI_SELFTEST_WHISPER=1 なら小さいモデルで実際に聴き取る（要ネット）
    import os

    from musicai import asr

    whisper = asr.backend()
    if os.environ.get("MUSICAI_SELFTEST_WHISPER") == "1":
        assert whisper, "Whisper が同梱されていません"
        import numpy as np

        t = np.arange(16000 * 3) / 16000
        tone = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        segs = asr.transcribe(tone, "tiny")
        print("WHISPER OK", whisper, len(segs), "segments")
    print("SELFTEST OK", files, "->", service.OUTPUT_DIR, "| import:", res["log"][-2])
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # 絵文字が出せないコンソールでも落ちないように
        except Exception:
            pass
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    try:
        from musicai.app import run

        run()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        print("\n起動中にエラーが起きました。上のメッセージを開発者に伝えてください。")
        try:
            input("Enter キーで閉じます...")
        except EOFError:
            pass
