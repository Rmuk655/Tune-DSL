"""
Tune DSL — Standard MIDI File (SMF) exporter.

Exports a SemanticResult to a Format 1 (multi-track) .mid file: one MIDI
track per `play` statement, so each instrument lands on its own track/
channel in a DAW. Hand-rolled at the byte level (same approach as
reference.py's WAV writer) -- no MIDI library dependency for the writer
itself; `mido` is used only in the test suite as an independent reader
to validate correctness (same role `wave` plays for validating WAV output).

Scope note: MIDI represents NOTES (pitch, timing, velocity), not audio
signal processing -- `effect` statements (lowpass, delay, etc.) have no
MIDI equivalent and are simply not present in the exported file. This
is an inherent property of the MIDI format, not a bug: a MIDI file is a
performance/score representation, not a rendered audio signal.

PPQ (ticks per quarter note) = 480, and 1 beat = 1 quarter note, matching
the rest of Tune's convention (see reference.py's beats_to_seconds).
"""

import math
import struct

from semantic import SemanticResult

PPQ = 480  # ticks per quarter note (= ticks per beat, by Tune's convention)


def freq_to_midi_note(freq_hz: float) -> int:
    """Inverse of pitch.pitch_to_freq: nearest MIDI note number for a
    frequency. Exact (up to rounding) for any frequency pitch_to_freq
    produced, since both sides use the same A4=440, 12-TET assumptions."""
    return int(round(69 + 12.0 * math.log2(freq_hz / 440.0)))


def _write_var_len(value: int) -> bytes:
    """MIDI variable-length quantity encoding for delta-times."""
    if value < 0:
        raise ValueError("delta time cannot be negative")
    buf = [value & 0x7F]
    value >>= 7
    while value > 0:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(buf))


def _build_track_events(events, ppq: int):
    """Converts a list of NoteEvent (in beats) into a sorted list of
    (tick, event_type, note, velocity) tuples. event_type is 'on' or
    'off'. Rests and DCE'd (already-absent) events contribute nothing."""
    raw = []
    for ev in events:
        if ev.freq_hz is None:
            continue  # rest
        note = freq_to_midi_note(ev.freq_hz)
        note = max(0, min(127, note))
        vel = max(1, min(127, int(round(ev.velocity * 127))))
        start_tick = int(round(ev.start_beat * ppq))
        end_tick = int(round((ev.start_beat + ev.duration_beats) * ppq))
        if end_tick <= start_tick:
            end_tick = start_tick + 1
        raw.append((start_tick, "on", note, vel))
        raw.append((end_tick, "off", note, 0))
    # note-offs before note-ons at the same tick, so a note doesn't appear
    # to overlap itself if one ends exactly when another (same pitch) begins
    raw.sort(key=lambda e: (e[0], 0 if e[1] == "off" else 1))
    return raw


def _track_chunk(events, tempo_bpm=None) -> bytes:
    body = bytearray()
    if tempo_bpm is not None:
        micros_per_quarter = int(round(60_000_000 / tempo_bpm))
        body += _write_var_len(0)
        body += bytes([0xFF, 0x51, 0x03])
        body += micros_per_quarter.to_bytes(3, "big")

    prev_tick = 0
    for tick, kind, note, vel in events:
        delta = tick - prev_tick
        prev_tick = tick
        body += _write_var_len(delta)
        if kind == "on":
            body += bytes([0x90, note, vel])
        else:
            body += bytes([0x80, note, 0])

    body += _write_var_len(0)
    body += bytes([0xFF, 0x2F, 0x00])  # end of track

    return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)


def export_midi(result: SemanticResult, path: str, ppq: int = PPQ):
    """Writes a Format 1 SMF: one track per `play` statement (plus the
    tempo meta event on the first track)."""
    tracks = []
    for i, (_instrument, pattern) in enumerate(result.plays):
        events = _build_track_events(result.note_events[pattern], ppq)
        tempo = result.tempo_bpm if i == 0 else None
        tracks.append(_track_chunk(events, tempo))

    if not tracks:
        # no play statements: still produce a minimal valid file with an
        # empty tempo-only track, rather than an unreadable empty file
        tracks.append(_track_chunk([], result.tempo_bpm))

    num_tracks = len(tracks)
    header = (
        b"MThd" + struct.pack(">I", 6)
        + struct.pack(">H", 1)          # format 1
        + struct.pack(">H", num_tracks)
        + struct.pack(">H", ppq)
    )

    with open(path, "wb") as f:
        f.write(header)
        for t in tracks:
            f.write(t)