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
    print("SELFTEST OK", files, "->", service.OUTPUT_DIR)
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
