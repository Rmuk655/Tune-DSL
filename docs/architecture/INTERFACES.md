# Interfaces

The data shapes that cross module boundaries. If you're modifying one
module and need to know what another module expects from or hands to
it, this is the file to check.

## `Token` (produced by `lexer.py`, consumed by `parser.py`)

```
Token:
  type:  TokType   # INT, FLOAT, IDENT, PITCH, one per keyword,
                    #   one per symbol, NEWLINE, EOF
  value: str | float | int
  line:  int
  col:   int
```

`parser.py` never looks at source text directly — everything it needs
(including error positions) comes from `Token`.

## AST nodes (`ast_nodes.py`, produced by `parser.py`, consumed by `semantic.py`)

Plain dataclasses, one per grammar production in
[../language/03_LANGUAGE_REFERENCE_MANUAL.md §3.2](../language/03_LANGUAGE_REFERENCE_MANUAL.md#32-grammar):
expression nodes (`Num`, `Ident`, `Pitch`, `BinOp`, `UnaryOp`),
top-level nodes (`TempoStmt`, `InstrumentDecl`, `LetStmt`,
`PatternDecl`, `PlayStmt`, `EffectStmt`), and pattern-body nodes
(`NoteStmt`, `ChordStmt`, `RestStmt`, `RepeatStmt`, `SlideStmt`,
`StrumStmt`), rooted at `Program(statements)`. Every node carries
`line`/`col` for error messages. No node has behavior — `semantic.py`
is the only module that interprets them.

## `NoteEvent` (produced and consumed within `semantic.py`; consumed by every backend)

```
NoteEvent:
  freq_hz:          float | None   # None = rest
  start_beat:       float
  duration_beats:   float
  waveform:         str            # one of the 6 waveform names
  velocity:         float = 1.0
  slide_from_freq:  float | None = None   # set only for a slide event
  attack_sec:       float | None = None   # None = use the backend's default (~5ms)
  release_sec:      float | None = None
```

This is **the** representation every synthesis backend renders from —
none of them ever sees the AST. A backend can therefore be written
knowing only this shape and
[03_LANGUAGE_REFERENCE_MANUAL.md §3.5](../language/03_LANGUAGE_REFERENCE_MANUAL.md#35-pattern-body-statements)'s
description of what produced each field.

## `SemanticResult` (produced by `semantic.py`; consumed by every backend, `midi_export.py`, and `gui/app.py`)

```
SemanticResult:
  tempo_bpm:        float
  instruments:      dict[str, str]                 # name -> waveform
  note_events:      dict[str, list[NoteEvent]]      # pattern name -> flattened events
  plays:            list[tuple[str, str]]           # (instrument, pattern) pairs
  effects:          list[tuple[str, list[float]]]   # (effect name, args), in declared order
  dce_eliminated:   int                              # count of velocity-0 events elided
```

A backend renders `plays`: for each `(instrument, pattern)` pair, look
up `note_events[pattern]` and mix it in (all `play`s start at beat 0 —
see
[03_LANGUAGE_REFERENCE_MANUAL.md §3.3](../language/03_LANGUAGE_REFERENCE_MANUAL.md#33-top-level-statements)).
`effects` is applied once, to the whole finished mix, in list order.

**Caveat carried over from [DECISIONS.md, ARCH-005](DECISIONS.md#arch-005-one-flattened-event-list-per-pattern-name-not-per-instrumentpattern-pair):**
`note_events` is keyed by pattern name alone, not by `(instrument,
pattern)` — if the same pattern name is `play`ed by two different
instruments, both reuse whichever instrument's waveform/envelope was
resolved first.

## What each backend additionally needs from `SemanticResult`

- **`reference.py`** needs nothing beyond the shape above; it renders
  directly from it.
- **`codegen.py`** / **`codegen_mlir.py`** first scan every event for
  `slide_from_freq is not None` or `attack_sec`/`release_sec` not
  `None`, and raise `CppBackendError`/`MlirBackendError` immediately if
  found (§[DECISIONS.md, ARCH-004](DECISIONS.md#arch-004-hard-error-not-silent-feature-drop-for-backend-gaps)),
  *before* generating any code. Otherwise they precompute, per event,
  `start_sample`/`n_samples` (rounded in Python — see
  [DECISIONS.md, ARCH-001](DECISIONS.md#arch-001-round-durations-in-python-not-c)),
  a waveform-id integer, and an effect-id integer, then bake those into
  generated source.
- **`midi_export.py`** needs `tempo_bpm`, `plays`, and `note_events`
  only — `effects` is read by nothing downstream of it, since MIDI has
  no representation for audio effects.

## `chord_theory.resolve_chord()` (produced by `chord_theory.py`, consumed by `chordsheet.py`)

```
resolve_chord(symbol: str, base_octave: int) -> list[str]   # pitch names, e.g. ["C4","E4","G4"]
```

Input is a chord symbol as described in
[03_LANGUAGE_REFERENCE_MANUAL.md §3.10](../language/03_LANGUAGE_REFERENCE_MANUAL.md#310-chord-sheets)
(`"Am7"`, `"C/E"`, ...). Output is a list of Tune-syntax pitch names
(`s`/`b` spelling, matching `pitch.py`'s expectations) — a slash chord
prepends one extra bass pitch, one octave below `base_octave`.

## `chordsheet_to_tune()` (produced by `chordsheet.py`, consumed by `chordsheet_cli.py`, which feeds it back into `lexer.py`)

```
chordsheet_to_tune(text: str, instrument_key: str,
                    instrument_name: str | None = None,
                    pattern_name: str | None = None,
                    include_tempo: bool = True) -> str    # Tune DSL source text
```

`instrument_key` must be one of `INSTRUMENT_DEFAULTS`'s file
extensions (§3.10). The returned string is plain Tune source — it is
not a distinct AST or intermediate form; `chordsheet_cli.py` runs it
through the exact same `lexer.py`/`parser.py`/`semantic.py` pipeline as
any hand-written `.tune` file.

## HTTP JSON shapes (`gui/app.py`)

`POST /api/compile` request: `{"source": str, "backend": "python"|"cpp"|"mlir"}`.
Success response: `{"ok": true, "audio_url": str, "warning": str|None,
"tempo": float, "duration": float, "dce_eliminated": int,
"num_instruments": int, "num_plays": int}` — every field beyond
`audio_url` is read directly off `SemanticResult` plus the rendered
buffer's length, not recomputed independently.
Failure response: `{"ok": false, "error": str}`.
See [../architecture/06_COMPILER_ARCHITECTURE.md §6.7](06_COMPILER_ARCHITECTURE.md#67-the-gui-is-not-a-separate-implementation).
