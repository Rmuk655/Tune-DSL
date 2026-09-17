import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from chord_theory import parse_chord_symbol, resolve_chord, ChordError


def test_bare_major_chord():
    assert parse_chord_symbol("C") == ("C", "", None)


def test_minor_chord():
    assert parse_chord_symbol("Am") == ("A", "m", None)


def test_dominant_seventh():
    assert parse_chord_symbol("G7") == ("G", "7", None)


def test_minor_seventh_not_confused_with_bare_minor():
    # regression-style check: "m7" must not be parsed as "m" + leftover "7"
    assert parse_chord_symbol("Dm7") == ("D", "m7", None)


def test_major_seventh():
    assert parse_chord_symbol("Fmaj7") == ("F", "maj7", None)


def test_sharp_and_flat_roots():
    assert parse_chord_symbol("C#m") == ("C#", "m", None)
    assert parse_chord_symbol("Bbmaj7") == ("Bb", "maj7", None)


def test_slash_chord():
    assert parse_chord_symbol("G/B") == ("G", "", "B")
    assert parse_chord_symbol("Dm7/F") == ("D", "m7", "F")


def test_sus_and_dim_and_aug():
    assert parse_chord_symbol("Csus4") == ("C", "sus4", None)
    assert parse_chord_symbol("Bdim") == ("B", "dim", None)
    assert parse_chord_symbol("Faug") == ("F", "aug", None)


def test_power_chord():
    assert parse_chord_symbol("E5") == ("E", "5", None)


def test_invalid_chord_raises():
    with pytest.raises(ChordError):
        parse_chord_symbol("H")  # not a valid root letter
    with pytest.raises(ChordError):
        parse_chord_symbol("Cxyz")  # not a recognized quality


# -- resolve_chord: actual music-theory correctness --

def test_c_major_triad():
    assert resolve_chord("C", base_octave=4) == ["C4", "E4", "G4"]


def test_a_minor_triad():
    assert resolve_chord("Am", base_octave=4) == ["A4", "C5", "E5"]  # C,E wrap to octave 5


def test_g_dominant_seventh():
    assert resolve_chord("G7", base_octave=3) == ["G3", "B3", "D4", "F4"]


def test_f_major_seventh():
    assert resolve_chord("Fmaj7", base_octave=4) == ["F4", "A4", "C5", "E5"]


def test_d_minor_seventh():
    assert resolve_chord("Dm7", base_octave=4) == ["D4", "F4", "A4", "C5"]


def test_slash_chord_adds_bass_note_below():
    notes = resolve_chord("G/B", base_octave=4)
    assert notes[0] == "B3"  # bass note, one octave below base
    assert notes[1:] == ["G4", "B4", "D5"]


def test_power_chord_two_notes():
    assert resolve_chord("E5", base_octave=3) == ["E3", "B3"]


def test_sus4_chord():
    assert resolve_chord("Csus4", base_octave=4) == ["C4", "F4", "G4"]


def test_octave_wrap_is_consistent_going_up_chromatically():
    # sanity check across all 12 roots: every resolved note should be
    # parseable by pitch.py's own pitch_to_freq (proves valid spelling)
    from pitch import pitch_to_freq
    for root in ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]:
        notes = resolve_chord(root, base_octave=3)
        for n in notes:
            pitch_to_freq(n)  # must not raise


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))