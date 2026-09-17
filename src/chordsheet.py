"""
Tune DSL — chord-sheet format parser and converter to Tune source.

FORMAT (a `.guitar`, `.keyboard`, `.veena`, etc. file):

    # comments start with #
    tempo 96
    beats_per_chord 4

    C G Am F
    C G F C:2 Am:2

Each non-directive line is a row of space-separated chord symbols (see
chord_theory.py for supported chord syntax: C, Am, G7, Fmaj7, Dm7, C/E,
Csus4, etc). Each chord gets `beats_per_chord` beats by default; append
`:N` to a chord to give it N beats instead (e.g. `C:2` = 2 beats), or
`*N` to repeat it for N bars (e.g. `C*2` = 2 full bars of beats_per_chord
each).

HONESTY NOTE (important, not just a formality): a chord name carries
harmony, not rhythm. This format asks YOU to supply the tempo and
per-chord durations (by listening to the reference recording and
matching what you hear) -- there is no way to derive "the tempo of this
recording" or "how many beats each chord gets" from chord names alone.
What this DOES give you: a fast, deterministic way to turn a chord
progression + rhythm you've worked out by ear into real compiled audio,
on your choice of instrument voice, and to layer several instruments'
chord sheets together into one arrangement. It will not spontaneously
match a specific recording's exact drum pattern, strum feel, or voicings
-- those aren't present in a chord sheet, by the nature of chord sheets.

INSTRUMENT_DEFAULTS below assigns each instrument name a waveform,
register (octave), and whether it plays full chords or just the root
note (like a real bassline would) -- chosen to sound reasonably
differentiated using Tune's existing waveform palette (sine/square/saw/
triangle/pulse/noise). This is NOT physical-modeling synthesis of a real
guitar or veena's timbre (that's a fundamentally different, much larger
undertaking -- string body resonance, pluck excitation modeling, etc.);
it's a deliberate, honestly-scoped approximation using the synthesis
this project already has.
"""

import re

from chord_theory import resolve_chord, ChordError

# instrument name (matches the file extension, e.g. song.guitar) ->
# (waveform, base_octave, root_only). root_only=True means play just the
# chord's root/bass note (like a bass guitar), not the full chord.
INSTRUMENT_DEFAULTS = {
    "guitar":     ("pulse", 3, False),
    "keyboard":   ("sine", 4, False),
    "piano":      ("sine", 4, False),
    "veena":      ("saw", 4, False),
    "sitar":      ("saw", 4, False),
    "violin":     ("sine", 4, False),
    "flute":      ("triangle", 5, False),
    "mandolin":   ("pulse", 4, False),
    "bass":       ("square", 2, True),
    # additions common in Indian film/BGM arrangements:
    "harmonium":  ("triangle", 3, False),  # sustained drone-like chords, lower/warmer register
    "santoor":    ("pulse", 5, False),     # bright, struck/plucked, sits high in the mix
    "sarangi":    ("sine", 4, False),      # bowed, smooth like violin but its own register/voice
    "shehnai":    ("square", 5, False),    # reedy, piercing, festive/classical -- high register
    "synth":      ("saw", 4, False),       # modern Bollywood synth lead/pad
    "tabla":      ("noise", 2, True),      # percussive hits, not real chords -- see note below
}
# Note on "tabla": tabla is a percussion instrument -- it doesn't play
# chords or sustained pitches at all. Mapping it into this chord-sheet
# format is a deliberate, honest compromise: each chord-sheet "chord"
# becomes one rhythmic noise-waveform hit (root_only=True, and since the
# `noise` waveform ignores frequency entirely, the specific chord/root
# you write for a .tabla file only controls WHEN a hit lands, not its
# pitch). This gives you a way to add a percussive layer on the same
# beat grid as your other instruments -- it is not a tabla timbre
# simulation, which nothing here attempts.


class ChordSheetError(Exception):
    pass


_CHORD_TOKEN_RE = re.compile(r"^(?P<symbol>[^:*]+)(?:(?P<op>[:*])(?P<num>\d+))?$")


def parse_chordsheet(text: str):
    """Returns (tempo_bpm_or_None, [(chord_symbol, beats), ...])."""
    tempo = None
    beats_per_chord = 4
    entries = []

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        parts = line.split()
        if parts[0] == "tempo" and len(parts) == 2:
            try:
                tempo = float(parts[1])
            except ValueError:
                raise ChordSheetError(f"line {lineno}: invalid tempo {parts[1]!r}")
            continue
        if parts[0] == "beats_per_chord" and len(parts) == 2:
            try:
                beats_per_chord = int(parts[1])
            except ValueError:
                raise ChordSheetError(f"line {lineno}: invalid beats_per_chord {parts[1]!r}")
            continue

        for token in parts:
            m = _CHORD_TOKEN_RE.match(token)
            if not m:
                raise ChordSheetError(f"line {lineno}: unparsable chord token {token!r}")
            symbol = m.group("symbol")
            op = m.group("op")
            num = int(m.group("num")) if m.group("num") else None
            if op == ":":
                entries.append((symbol, num))
            elif op == "*":
                for _ in range(num):
                    entries.append((symbol, beats_per_chord))
            else:
                entries.append((symbol, beats_per_chord))

    return tempo, entries


def chordsheet_to_tune(text: str, instrument_key: str, instrument_name: str = None,
                        pattern_name: str = None, include_tempo: bool = True) -> str:
    """Converts chord-sheet text into Tune DSL source: one `instrument`
    declaration, one `pattern` with a `chord [...] : <beats>` line per
    entry, and one `play` statement. include_tempo=False omits the
    `tempo` line even if the sheet specifies one -- used when merging
    several instruments' sheets into one combined file, where the
    combined tempo is decided once by the caller, not per-file."""
    if instrument_key not in INSTRUMENT_DEFAULTS:
        raise ChordSheetError(
            f"unknown instrument {instrument_key!r} "
            f"(supported: {sorted(INSTRUMENT_DEFAULTS)})"
        )
    waveform, base_octave, root_only = INSTRUMENT_DEFAULTS[instrument_key]
    instrument_name = instrument_name or instrument_key
    pattern_name = pattern_name or f"{instrument_key}_pattern"

    tempo, entries = parse_chordsheet(text)
    if not entries:
        raise ChordSheetError("chord sheet contains no chords")

    lines = []
    if include_tempo and tempo is not None:
        lines.append(f"tempo {tempo:g}")
    lines.append(f"instrument {instrument_name} = {waveform}")
    lines.append(f"pattern {pattern_name} {{")
    for symbol, beats in entries:
        try:
            notes = resolve_chord(symbol, base_octave=base_octave)
        except ChordError as e:
            raise ChordSheetError(str(e))
        if root_only:
            lines.append(f"  note {notes[0]} : {beats}")
        else:
            chord_list = ", ".join(notes)
            lines.append(f"  chord [{chord_list}] : {beats}")
    lines.append("}")
    lines.append(f"play {instrument_name} {pattern_name}")
    lines.append("")

    return "\n".join(lines)