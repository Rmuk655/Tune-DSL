import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import math
import pytest
from pitch import pitch_to_freq, parse_pitch_name, PitchError


def approx(a, b, tol=0.01):
    return abs(a - b) < tol


def test_a4_is_440():
    assert approx(pitch_to_freq("A4"), 440.0)


def test_c4_middle_c():
    # well-known reference value
    assert approx(pitch_to_freq("C4"), 261.63, tol=0.01)


def test_a5_is_double_a4():
    assert approx(pitch_to_freq("A5"), 880.0)


def test_a3_is_half_a4():
    assert approx(pitch_to_freq("A3"), 220.0)


def test_sharp_flat_enharmonic_equivalence():
    # Cs4 and Db4 must be the exact same frequency
    assert pitch_to_freq("Cs4") == pitch_to_freq("Db4")
    assert pitch_to_freq("As3") == pitch_to_freq("Bb3")
    assert pitch_to_freq("Fs5") == pitch_to_freq("Gb5")


def test_octave_boundary_b_to_c():
    # B3 should be just below C4, not above it
    b3 = pitch_to_freq("B3")
    c4 = pitch_to_freq("C4")
    assert b3 < c4
    # and exactly one semitone apart: ratio should be 2^(1/12)
    assert approx(c4 / b3, 2 ** (1 / 12), tol=0.001)


def test_octave_doubles_frequency():
    c4 = pitch_to_freq("C4")
    c5 = pitch_to_freq("C5")
    assert approx(c5 / c4, 2.0, tol=0.0001)


def test_parse_pitch_name_simple():
    assert parse_pitch_name("C4") == ("C", 4)


def test_parse_pitch_name_sharp():
    assert parse_pitch_name("Cs4") == ("Cs", 4)


def test_parse_pitch_name_flat():
    assert parse_pitch_name("Bb3") == ("Bb", 3)


def test_unknown_pitch_class_raises():
    with pytest.raises(PitchError):
        pitch_to_freq("H4")


def test_all_twelve_semitones_within_octave_are_increasing():
    names = ["C4", "Cs4", "D4", "Ds4", "E4", "F4", "Fs4", "G4", "Gs4", "A4", "As4", "B4"]
    freqs = [pitch_to_freq(n) for n in names]
    for i in range(len(freqs) - 1):
        assert freqs[i] < freqs[i + 1], f"{names[i]} should be < {names[i+1]}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))