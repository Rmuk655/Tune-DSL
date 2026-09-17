import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import shutil
import pytest

from parser import parse
from semantic import analyze
from midi_export import export_midi, freq_to_midi_note
from pitch import pitch_to_freq

try:
    import mido
    HAVE_MIDO = True
except ImportError:
    HAVE_MIDO = False

requires_mido = pytest.mark.skipif(not HAVE_MIDO, reason="mido not installed")


def test_freq_to_midi_note_middle_c():
    assert freq_to_midi_note(pitch_to_freq("C4")) == 60


def test_freq_to_midi_note_a4_is_69():
    assert freq_to_midi_note(440.0) == 69


def test_freq_to_midi_note_roundtrips_all_pitches():
    # every pitch our own pitch.py can produce should map back to the
    # exact expected MIDI note number (60 = C4 convention)
    names_and_midi = [
        ("C4", 60), ("Cs4", 61), ("D4", 62), ("E4", 64), ("G4", 67),
        ("A4", 69), ("B4", 71), ("C5", 72), ("C3", 48), ("A0", 21),
    ]
    for name, expected_midi in names_and_midi:
        assert freq_to_midi_note(pitch_to_freq(name)) == expected_midi, name


@requires_mido
def test_export_produces_valid_midi_file(tmp_path):
    src = "instrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    result = analyze(parse(src))
    path = str(tmp_path / "out.mid")
    export_midi(result, path)
    mid = mido.MidiFile(path)  # raises if malformed
    assert mid.type == 1
    assert len(mid.tracks) == 1


@requires_mido
def test_tempo_meta_event_matches_source():
    import tempfile
    src = "tempo 140\ninstrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    result = analyze(parse(src))
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.mid")
        export_midi(result, path)
        mid = mido.MidiFile(path)
        tempo_msgs = [m for m in mid.tracks[0] if m.type == "set_tempo"]
        assert len(tempo_msgs) == 1
        bpm = mido.tempo2bpm(tempo_msgs[0].tempo)
        assert abs(bpm - 140) < 0.01


@requires_mido
def test_note_pitch_and_timing(tmp_path):
    src = (
        "tempo 120\ninstrument lead = sine\n"
        "pattern m {\n  note C4 : 1/4\n  note E4 : 1/4\n}\nplay lead m\n"
    )
    result = analyze(parse(src))
    path = str(tmp_path / "out.mid")
    export_midi(result, path)
    mid = mido.MidiFile(path)

    notes = []
    abs_tick = 0
    for msg in mid.tracks[0]:
        abs_tick += msg.time
        if msg.type == "note_on":
            notes.append((msg.note, abs_tick))
    assert notes == [(60, 0), (64, 120)]  # C4 at tick 0, E4 at tick 120 (1/4 beat @ 480 ppq)


@requires_mido
def test_velocity_maps_to_midi_range(tmp_path):
    src = (
        "instrument lead = sine\n"
        "pattern m {\n  note C4 : 1/4 @ 1.0\n  note E4 : 1/4 @ 0.5\n}\nplay lead m\n"
    )
    result = analyze(parse(src))
    path = str(tmp_path / "out.mid")
    export_midi(result, path)
    mid = mido.MidiFile(path)
    velocities = [msg.velocity for msg in mid.tracks[0] if msg.type == "note_on"]
    assert velocities == [127, 64]  # round(1.0*127)=127, round(0.5*127)=round(63.5)=64 (half-to-even)


@requires_mido
def test_chord_produces_simultaneous_note_ons(tmp_path):
    src = "instrument lead = sine\npattern m { chord [C4, E4, G4] : 1/2 }\nplay lead m\n"
    result = analyze(parse(src))
    path = str(tmp_path / "out.mid")
    export_midi(result, path)
    mid = mido.MidiFile(path)

    note_ons = [msg for msg in mid.tracks[0] if msg.type == "note_on"]
    assert len(note_ons) == 3
    assert note_ons[0].time == 0
    assert note_ons[1].time == 0  # simultaneous: same tick as first
    assert note_ons[2].time == 0
    assert sorted(m.note for m in note_ons) == [60, 64, 67]


@requires_mido
def test_rest_produces_no_note_events(tmp_path):
    src = (
        "instrument lead = sine\n"
        "pattern m {\n  note C4 : 1/4\n  rest : 1/4\n  note E4 : 1/4\n}\nplay lead m\n"
    )
    result = analyze(parse(src))
    path = str(tmp_path / "out.mid")
    export_midi(result, path)
    mid = mido.MidiFile(path)
    note_ons = [msg for msg in mid.tracks[0] if msg.type == "note_on"]
    assert len(note_ons) == 2  # rest contributes no event, just a timing gap


@requires_mido
def test_multiple_plays_produce_separate_tracks(tmp_path):
    src = (
        "instrument lead = sine\ninstrument bass = square\n"
        "pattern hi { note C5 : 1/4 }\npattern lo { note C3 : 1/4 }\n"
        "play lead hi\nplay bass lo\n"
    )
    result = analyze(parse(src))
    path = str(tmp_path / "out.mid")
    export_midi(result, path)
    mid = mido.MidiFile(path)
    assert len(mid.tracks) == 2
    track0_notes = [m.note for m in mid.tracks[0] if m.type == "note_on"]
    track1_notes = [m.note for m in mid.tracks[1] if m.type == "note_on"]
    assert track0_notes == [72]  # C5
    assert track1_notes == [48]  # C3


@requires_mido
def test_dce_eliminated_notes_absent_from_midi(tmp_path):
    # zero-velocity notes are dropped during semantic analysis (DCE) --
    # confirm that propagates all the way through to the exported file
    src = (
        "instrument lead = sine\n"
        "pattern m {\n  note C4 : 1/4 @ 0\n  note E4 : 1/4\n}\nplay lead m\n"
    )
    result = analyze(parse(src))
    path = str(tmp_path / "out.mid")
    export_midi(result, path)
    mid = mido.MidiFile(path)
    note_ons = [msg.note for msg in mid.tracks[0] if msg.type == "note_on"]
    assert note_ons == [64]  # only E4, C4 was eliminated


@requires_mido
def test_no_play_statements_still_produces_valid_file(tmp_path):
    src = "instrument lead = sine\npattern m { note C4 : 1/4 }\n"  # no play
    result = analyze(parse(src))
    path = str(tmp_path / "out.mid")
    export_midi(result, path)
    mid = mido.MidiFile(path)  # must not raise
    assert len(mid.tracks) == 1


@requires_mido
def test_repeat_unrolled_notes_all_present(tmp_path):
    src = (
        "instrument lead = sine\n"
        "pattern m {\n  repeat 3 {\n    note C4 : 1/4\n  }\n}\nplay lead m\n"
    )
    result = analyze(parse(src))
    path = str(tmp_path / "out.mid")
    export_midi(result, path)
    mid = mido.MidiFile(path)
    note_ons = [msg for msg in mid.tracks[0] if msg.type == "note_on"]
    assert len(note_ons) == 3


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))