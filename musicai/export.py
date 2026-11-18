"""書き出し: MIDI（歌詞つき）/ MusicXML（歌詞つき楽譜）/ 歌詞カード。

MusicXML は NEUTRINO・Synthesizer V・MuseScore などで開ける。
歌声合成ソフトに読み込めば、仮歌シンセではなく本物の歌声で歌わせられる。
"""
from __future__ import annotations

import struct
from fractions import Fraction
from pathlib import Path
from xml.sax.saxutils import escape

from .arrange import Arrangement
from .lyrics import display_lyrics
from .song import Song
from .theory import pc_name

TPB = 480

GM = {"vocal": (0, 54), "piano": (1, 0), "pad": (2, 89), "guitar": (3, 29), "bass": (4, 33), "drums": (9, 0)}


def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def _track(events: list[tuple[int, bytes]]) -> bytes:
    events.sort(key=lambda e: e[0])
    data = bytearray()
    last = 0
    for tick, msg in events:
        data += _vlq(tick - last) + msg
        last = tick
    data += _vlq(0) + b"\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(data)) + bytes(data)


def _meta(kind: int, payload: bytes) -> bytes:
    return bytes([0xFF, kind]) + _vlq(len(payload)) + payload


def write_midi(song: Song, arr: Arrangement, path: str | Path) -> None:
    tracks = []
    mpqn = int(60_000_000 / song.tempo)
    conductor = [
        (0, _meta(0x03, song.title.encode("utf-8"))),
        (0, _meta(0x51, mpqn.to_bytes(3, "big"))),
        (0, _meta(0x58, bytes([song.beats_per_bar, 2, 24, 8]))),
        (0, _meta(0x59, struct.pack(">bB", song.key.fifths, 1 if song.key.mode == "minor" else 0))),
    ]
    t = 0
    for start, sec in song.timeline():
        conductor.append((int(start * TPB), _meta(0x06, sec.name.encode("utf-8"))))
    tracks.append(_track(conductor))
    for name, evs in arr.tracks.items():
        ch, prog = GM.get(name, (5, 0))
        msgs = [(0, _meta(0x03, name.encode())), (0, bytes([0xC0 | ch, prog]))]
        for ev in evs:
            on = int(round(ev.start * TPB))
            off = max(on + 1, int(round((ev.start + ev.dur) * TPB)) - (2 if name == "vocal" else 0))
            vel = max(1, min(127, int(ev.vel * 127)))
            if name == "vocal" and ev.lyric:
                try:
                    txt = ev.lyric.encode("shift_jis")
                except UnicodeEncodeError:
                    txt = ev.lyric.encode("utf-8")
                msgs.append((on, _meta(0x05, txt)))
            msgs.append((off, bytes([0x80 | ch, ev.pitch, 0])))
            msgs.append((on, bytes([0x90 | ch, ev.pitch, vel])))
        # 同時刻なら note-off を先に
        msgs.sort(key=lambda e: (e[0], 0 if e[1][0] & 0xF0 == 0x80 else 1))
        tracks.append(_track(msgs))
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), TPB)
    Path(path).write_bytes(header + b"".join(tracks))


# ---------------- MusicXML ----------------
DIV = 24  # 4 分音符 = 24（3 連符も表せる）
_TYPES = [(96, "whole", 0), (72, "half", 1), (48, "half", 0), (36, "quarter", 1), (24, "quarter", 0),
          (18, "eighth", 1), (12, "eighth", 0), (9, "16th", 1), (6, "16th", 0), (3, "32nd", 0)]


def _split_dur(div: int) -> list[tuple[int, str, int]]:
    out = []
    while div > 0:
        for d, tp, dots in _TYPES:
            if d <= div:
                out.append((d, tp, dots))
                div -= d
                break
        else:
            out.append((div, "32nd", 0))
            div = 0
    return out


def write_musicxml(song: Song, path: str | Path) -> None:
    bpb = song.beats_per_bar
    bar_div = bpb * DIV
    flat = song.key.prefer_flat
    # 全セクションの音符を (開始div, 長さdiv, pitch, lyric, melisma) に
    items = []
    harmonies = []
    for start, sec in song.timeline():
        t = int(start * DIV)
        for cs, cd, nm in sec.chords:
            harmonies.append((int((start + cs) * DIV), nm))
        for n in sec.notes:
            if not sec.sing:  # 歌わないパート（間奏など）は休符
                d = int(n.dur * DIV)
                items.append((t, d, None, None))
                t += d
                continue
            d = int(n.dur * DIV)
            items.append((t, d, n.pitch, n.lyric.text if (n.lyric and not n.lyric.melisma) else None))
            t += d
        sec_end = int((start + sec.length) * DIV)
        if t < sec_end:
            items.append((t, sec_end - t, None, None))
    total = items[-1][0] + items[-1][1] if items else bar_div
    n_bars = -(-total // bar_div)
    if total < n_bars * bar_div:
        items.append((total, n_bars * bar_div - total, None, None))

    measures: list[list[str]] = [[] for _ in range(n_bars)]
    harm_by_bar: dict[int, list[tuple[int, str]]] = {}
    for hs, nm in harmonies:
        harm_by_bar.setdefault(hs // bar_div, []).append((hs % bar_div, nm))

    for (t, d, pitch, lyric) in items:
        first = True
        while d > 0:
            bar = t // bar_div
            room = bar_div - t % bar_div
            seg = min(d, room)
            pieces = _split_dur(seg)
            for k, (pd, tp, dots) in enumerate(pieces):
                last_piece = (d - seg == 0) and k == len(pieces) - 1
                xml = ["<note>"]
                if pitch is None:
                    xml.append("<rest/>")
                else:
                    pc = pitch % 12
                    name = pc_name(pc, flat)
                    alter = 1 if "#" in name else (-1 if "b" in name else 0)
                    xml.append(f"<pitch><step>{name[0]}</step>"
                               + (f"<alter>{alter}</alter>" if alter else "")
                               + f"<octave>{pitch // 12 - 1}</octave></pitch>")
                xml.append(f"<duration>{pd}</duration>")
                if pitch is not None:
                    if not first:
                        xml.append('<tie type="stop"/>')
                    if not last_piece:
                        xml.append('<tie type="start"/>')
                xml.append(f"<type>{tp}</type>" + "<dot/>" * dots)
                if pitch is not None and (not first or not last_piece):
                    tied = []
                    if not first:
                        tied.append('<tied type="stop"/>')
                    if not last_piece:
                        tied.append('<tied type="start"/>')
                    xml.append("<notations>" + "".join(tied) + "</notations>")
                if pitch is not None and first and lyric:
                    xml.append(f'<lyric number="1"><syllabic>single</syllabic><text>{escape(lyric)}</text></lyric>')
                xml.append("</note>")
                measures[bar].append((t % bar_div, "".join(xml)))
                t += pd
                first = False
            d -= seg

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" '
           '"http://www.musicxml.org/dtds/partwise.dtd">',
           '<score-partwise version="3.1">',
           f"<work><work-title>{escape(song.title)}</work-title></work>",
           '<part-list><score-part id="P1"><part-name>Vocal</part-name></score-part></part-list>',
           '<part id="P1">']
    for i, notes in enumerate(measures):
        out.append(f'<measure number="{i + 1}">')
        if i == 0:
            out.append(f"<attributes><divisions>{DIV}</divisions><key><fifths>{song.key.fifths}</fifths>"
                       f"<mode>{song.key.mode}</mode></key><time><beats>{bpb}</beats><beat-type>4</beat-type></time>"
                       "<clef><sign>G</sign><line>2</line></clef></attributes>")
            out.append(f'<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
                       f'<per-minute>{song.tempo:g}</per-minute></metronome></direction-type>'
                       f'<sound tempo="{song.tempo:g}"/></direction>')
        harms = sorted(harm_by_bar.get(i, []))
        events = [(pos, 0, _harmony_xml(nm, flat)) for pos, nm in harms] + [(pos, 1, x) for pos, x in notes]
        # harmony は対応する位置の音符の直前に
        for pos, _, x in sorted(events, key=lambda e: (e[0], e[1])):
            out.append(x)
        out.append("</measure>")
    out.append("</part></score-partwise>")
    Path(path).write_text("\n".join(out), encoding="utf-8")


def _harmony_xml(name: str, flat: bool) -> str:
    from .theory import parse_chord

    if name == "N.C.":
        return ""
    ch = parse_chord(name)
    root = pc_name(ch.root, flat)
    alter = 1 if "#" in root else (-1 if "b" in root else 0)
    qual = name.split("/")[0][len(root):] if name.startswith(root) else ""
    kind_map = {"": "major", "m": "minor", "7": "dominant", "maj7": "major-seventh", "M7": "major-seventh",
                "m7": "minor-seventh", "dim": "diminished", "dim7": "diminished-seventh", "aug": "augmented",
                "m7b5": "half-diminished", "sus4": "suspended-fourth", "sus2": "suspended-second",
                "6": "major-sixth", "m6": "minor-sixth", "9": "dominant-ninth"}
    kind = kind_map.get(qual, "major")
    return (f"<harmony><root><root-step>{root[0]}</root-step>"
            + (f"<root-alter>{alter}</root-alter>" if alter else "")
            + f'</root><kind text="{escape(qual)}">{kind}</kind></harmony>')


def lyric_sheet(song: Song) -> str:
    lines = [f"『{song.title}』", f"key: {song.key.name()} / tempo: {song.tempo:g}", ""]
    for name in song.structure:
        sec = song.sections[name]
        chords = " ".join(dict.fromkeys(c[2] for c in sec.chords if c[2] != "N.C."))
        lines.append(f"【{name}】  ({chords})")
        if sec.lyrics_text:
            lines.extend("  " + l for l in display_lyrics(sec.lyrics_text))
        else:
            lines.append("  （インスト）")
        lines.append("")
    return "\n".join(lines)
