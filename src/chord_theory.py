"""
Tune DSL — chord theory: parsing chord symbols (e.g. "Am7", "G/B", "Fmaj7")
and resolving them to actual pitch names Tune's `chord [...]` syntax uses.

This is real music theory, not guesswork: each chord quality is defined
by its semitone intervals from the root (standard tertian harmony), and
resolving a chord means finding the correct note name at root+interval
within a chosen octave, wrapping the octave up when an interval crosses
a C boundary (e.g. A + a major third = C#, one octave up from A's own
octave if A is spelled near the top of its octave).
"""

import re

# canonical semitone-index -> name, preferring sharps (matches pitch.py's
# PITCH_CLASS_SEMITONE table, which is keyed the same way)
_SEMITONE_TO_NAME = ["C", "Cs", "D", "Ds", "E", "F", "Fs", "G", "Gs", "A", "As", "B"]

_ROOT_SEMITONE = {
    "C": 0, "B#": 0,
    "C#": 1, "Db": 1,
    "D": 2,
    "D#": 3, "Eb": 3,
    "E": 4, "Fb": 4,
    "E#": 5, "F": 5,
    "F#": 6, "Gb": 6,
    "G": 7,
    "G#": 8, "Ab": 8,
    "A": 9,
    "A#": 10, "Bb": 10,
    "B": 11, "Cb": 11,
}

# chord quality -> semitone intervals from the root. Ordered roughly by
# how commonly they appear in pop/film chord sheets.
CHORD_QUALITIES = {
    "":     [0, 4, 7],       # major (bare root letter, e.g. "C")
    "maj":  [0, 4, 7],
    "m":    [0, 3, 7],       # minor
    "min":  [0, 3, 7],
    "7":    [0, 4, 7, 10],   # dominant 7th
    "maj7": [0, 4, 7, 11],
    "M7":   [0, 4, 7, 11],
    "m7":   [0, 3, 7, 10],
    "min7": [0, 3, 7, 10],
    "sus2": [0, 2, 7],
    "sus4": [0, 5, 7],
    "dim":  [0, 3, 6],
    "dim7": [0, 3, 6, 9],
    "aug":  [0, 4, 8],
    "5":    [0, 7],          # power chord
    "6":    [0, 4, 7, 9],
    "m6":   [0, 3, 7, 9],
    "9":    [0, 4, 7, 10, 14],
    "add9": [0, 4, 7, 14],
}

_CHORD_RE = re.compile(
    r"^(?P<root>[A-G](?:#|b)?)"
    r"(?P<quality>maj7|min7|dim7|sus2|sus4|add9|maj|min|dim|aug|m6|m7|m|M7|[0-9]+)?"
    r"(?:/(?P<bass>[A-G](?:#|b)?))?$"
)


class ChordError(Exception):
    pass


def parse_chord_symbol(symbol: str):
    """Parses e.g. "Am7", "G/B", "C", "F#dim" into (root, quality, bass).
    bass is None unless a slash chord was given."""
    m = _CHORD_RE.match(symbol)
    if not m:
        raise ChordError(f"unrecognized chord symbol {symbol!r}")
    root = m.group("root")
    quality = m.group("quality") or ""
    bass = m.group("bass")
    if quality not in CHORD_QUALITIES:
        raise ChordError(f"unrecognized chord quality {quality!r} in {symbol!r}")
    return root, quality, bass


def _semitone_to_pitch_name(semitone_abs: int, base_octave: int) -> str:
    """semitone_abs is a semitone count that may exceed 11 (meaning it
    wraps into a higher octave); returns e.g. 'Cs4'."""
    octave = base_octave + semitone_abs // 12
    name = _SEMITONE_TO_NAME[semitone_abs % 12]
    return f"{name}{octave}"


def resolve_chord(symbol: str, base_octave: int = 3):
    """Returns a list of Tune pitch-name strings (e.g. ['C3','E3','G3'])
    for the given chord symbol, voiced starting at base_octave. If the
    chord has a slash bass note, that note is prepended one octave below
    base_octave (a common, simple voicing choice for a bass note)."""
    root, quality, bass = parse_chord_symbol(symbol)
    root_semitone = _ROOT_SEMITONE[root]
    intervals = CHORD_QUALITIES[quality]

    notes = [_semitone_to_pitch_name(root_semitone + iv, base_octave) for iv in intervals]

    if bass is not None:
        bass_semitone = _ROOT_SEMITONE[bass]
        bass_note = _semitone_to_pitch_name(bass_semitone, base_octave - 1)
        notes = [bass_note] + notes

    return notes