"""
Tune DSL — pitch name -> frequency (Hz) conversion.

Equal temperament, A4 = 440 Hz. Semitone offsets are relative to A4,
within one octave (C..B), then shifted by octave number.

Standard convention: octave increments at C (so B3 is just below C4).
"""

import math

# semitone offset of each pitch class from C (within an octave)
_PITCH_CLASS_SEMITONE = {
    "C": 0, "Cs": 1, "Db": 1,
    "D": 2, "Ds": 3, "Eb": 3,
    "E": 4,
    "F": 5, "Fs": 6, "Gb": 6,
    "G": 7, "Gs": 8, "Ab": 8,
    "A": 9, "As": 10, "Bb": 10,
    "B": 11,
}

A4_FREQ = 440.0
A4_MIDI = 69  # MIDI note number for A4, used as the reference point


class PitchError(Exception):
    pass


def parse_pitch_name(name: str):
    """Split 'Cs4' -> ('Cs', 4), 'Bb3' -> ('Bb', 3), 'C4' -> ('C', 4)."""
    # digits are always the trailing octave (lexer already guarantees this
    # shape, but we re-validate here since this module has its own callers)
    i = len(name)
    while i > 0 and name[i - 1].isdigit():
        i -= 1
    if i == len(name):
        raise PitchError(f"pitch {name!r} has no octave digit")
    pitch_class = name[:i]
    octave_str = name[i:]
    try:
        octave = int(octave_str)
    except ValueError:
        raise PitchError(f"invalid octave in pitch {name!r}")
    if pitch_class not in _PITCH_CLASS_SEMITONE:
        raise PitchError(f"unknown pitch class {pitch_class!r} in {name!r}")
    return pitch_class, octave


def pitch_to_freq(name: str) -> float:
    """Convert e.g. 'C4', 'Cs4', 'Bb3' to a frequency in Hz."""
    pitch_class, octave = parse_pitch_name(name)
    semitone_in_octave = _PITCH_CLASS_SEMITONE[pitch_class]
    # MIDI note number: C4 = 60 in the common convention (A4 = 69)
    midi = (octave + 1) * 12 + semitone_in_octave
    semitones_from_a4 = midi - A4_MIDI
    return A4_FREQ * (2.0 ** (semitones_from_a4 / 12.0))