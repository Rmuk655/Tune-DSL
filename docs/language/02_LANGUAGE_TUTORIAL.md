# 2. Tune DSL Language Tutorial

A practical, example-driven walkthrough. Every example here is a
complete, valid, runnable `.tune` program — try compiling any of them
with `python3 tune.py <file>.tune`. For the precise, normative grammar
behind everything shown here, see
[03_LANGUAGE_REFERENCE_MANUAL.md](03_LANGUAGE_REFERENCE_MANUAL.md).

## 2.1 A Minimal Program

```tune
tempo 120
instrument lead = sine
pattern melody {
  note A4 : 1
}
play lead melody
```

Every program needs at least an `instrument`, a `pattern`, and a `play`
statement to produce audible output. `tempo` is optional (defaults to
120 BPM). Note that `1` here is **1 beat**, not 1 second — at 120 BPM,
one beat is 0.5 seconds, so this renders half a second of a 440Hz sine
tone.

## 2.2 Durations as Fractions of a Beat

Since `/` is ordinary division, write durations the way you'd read
music notation:

```tune
note C4 : 1     # quarter note (1 beat)
note C4 : 1/2   # eighth note
note C4 : 1/4   # sixteenth note
note C4 : 2     # half note
note C4 : 4     # whole note
```

## 2.3 Multiple Instruments Playing Together

```tune
tempo 100

instrument lead = sine
instrument bass = square

pattern melody {
  note C4 : 1/4
  note D4 : 1/4
  note E4 : 1/2
}

pattern bassline {
  note C3 : 1/2
  note G2 : 1/2
}

play lead melody
play bass bassline
```

**Every `play` statement starts at beat 0.** Multiple `play` lines
layer on top of each other rather than concatenating — this is how an
arrangement with several voices is built.

## 2.4 Chords

```tune
pattern chords {
  chord [C4, E4, G4] : 1        # C major
  chord [A3, C4, E4] : 1        # A minor
  chord [F3, A3, C4] : 1        # F major
  chord [G3, B3, D4] : 1        # G major
}
```

## 2.5 Velocity (Dynamics)

```tune
pattern dynamics {
  note C4 : 1/4 @ 1.0    # full volume
  note C4 : 1/4 @ 0.5    # half volume
  note C4 : 1/4 @ 0.1    # very quiet
  note C4 : 1/4 @ 0      # silent -- compiled away entirely, timing still advances
}
```

## 2.6 `let` Constants

```tune
let base_tempo = 96
let swing = 0.015

tempo base_tempo
effect delay swing 0.25
```

`let` is a compile-time constant, not a variable — it can't be
reassigned, and it must be declared before anything that references it.

## 2.7 `repeat` for Rhythmic Figures

```tune
pattern hats {
  repeat 8 {
    note C5 : 1/8 @ 0.3
  }
}
```

Repeats nest freely:

```tune
pattern figure {
  repeat 2 {
    note G4 : 1/8
    repeat 2 {
      note A4 : 1/16
    }
  }
}
```

## 2.8 Rests for Timing/Offsets

Since every `play` starts at beat 0, use `rest` to delay when a
particular instrument's part actually starts:

```tune
pattern late_entry {
  rest : 2            # wait two beats
  note C4 : 1/2
  note E4 : 1/2
}
```

## 2.9 `slide` (Pitch Glide)

```tune
instrument lead = sine
pattern lick {
  note C4 : 1/2
  slide G4 : 1/2       # smooth glide from C4 up to G4
}
play lead lick
```

`slide` needs a preceding pitched event **in the same pattern** to
glide from — using it as a pattern's first statement is a compile
error. It only renders on `--backend python`.

## 2.10 `strum` (Rolled Chords)

```tune
instrument guitar = pulse
pattern strummed {
  strum [C3, E3, G3] : 1 delay 0.03 @ 0.7
  strum [F3, A3, C4] : 1 delay 0.03 @ 0.7
}
play guitar strummed
```

Omit `delay` for the 20ms default: `strum [C3, E3, G3] : 1 @ 0.7`.

## 2.11 Per-Instrument Envelopes

```tune
instrument pad = pulse envelope 0.05 0.3   # slow attack, longer release
pattern padline {
  chord [C3, G3] : 4 @ 0.3
}
play pad padline
```

Without `envelope`, every backend uses a fixed short 5ms linear
fade-in/out — just enough to prevent clicks at note boundaries. Custom
`envelope` overrides only render on `--backend python`.

## 2.12 Global Effects

```tune
tempo 100

effect highpass 150
effect distortion 3
effect tremolo 5 0.4
effect lowpass 3000
effect delay 0.18 0.3

instrument lead = square
pattern riff {
  note C3 : 1/4 @ 0.9
  note E3 : 1/4 @ 0.7
  note G3 : 1/4 @ 0.9
  note C4 : 1/4 @ 1.0
}
play lead riff
```

Effects apply to the **entire final mix**, in declaration order, before
normalization — there's no syntax to scope an effect to one instrument
or pattern.

## 2.13 A Complete Example

```tune
tempo 100

effect lowpass 1800
effect delay 0.2 0.35

instrument lead = sine
instrument bass = square
instrument perc = noise
instrument pad  = pulse

pattern melody {
  note C4 : 1/4 @ 0.8
  note E4 : 1/4 @ 0.6
  chord [C4, E4, G4] : 1/2 @ 0.9
  repeat 2 {
    note G4 : 1/8 @ 0.4
    note A4 : 1/8 @ 0.4
  }
  note C5 : 1/2 @ 1.0
}

pattern bassline {
  note C3 : 1/2 @ 1.0
  note G2 : 1/2 @ 0.7
  note A2 : 1/2 @ 0.9
  note F2 : 1/2 @ 0.7
}

pattern hits {
  note C4 : 1/8 @ 0.3
  rest : 1/8
  note C4 : 1/8 @ 0.25
  rest : 1/8
}

pattern padline {
  chord [C3, G3] : 2 @ 0.25
}

play lead melody
play bass bassline
play perc hits
play pad padline
```

## 2.14 Writing Chord Progressions Instead of Notes

If you already know a song's chord progression by ear, the chord-sheet
format skips writing individual `note`/`chord` lines entirely — see
[03_LANGUAGE_REFERENCE_MANUAL.md §6](03_LANGUAGE_REFERENCE_MANUAL.md#6-chord-sheets)
for the full format:

```
# demo_song.guitar
tempo 96
beats_per_chord 4

C G Am F
C G F C:2 Am:2
```

```bash
python3 chordsheet_cli.py demo_song.guitar
# wrote demo_song.wav
```

## 2.15 Common Mistakes

| Symptom | Cause |
|---|---|
| `LexError: unexpected character` | Used a character like `♯`/`♭` instead of `s`/`b` in a pitch, or `#` in a non-comment position |
| `ParseError: expected NEWLINE, got ...` | Two statements on one line with no newline between them (a following `}` is the only exception) |
| `SemanticError: undefined variable` | Used a `let` name before declaring it, or misspelled it |
| `SemanticError: slide requires a preceding pitched note...` | `slide` was the first statement in its pattern |
| `error: the C++ backend does not yet support 'slide'...` | Used `--backend cpp`/`mlir` with `slide` or a custom `envelope` in the source |
| Output is silent | No `play` statement references your pattern, or every note has `@ 0` |

## 2.16 Where to Go Next

- [03_LANGUAGE_REFERENCE_MANUAL.md](03_LANGUAGE_REFERENCE_MANUAL.md) —
  the full grammar, every statement's exact semantics, backend feature
  matrix.
- [../architecture/06_COMPILER_ARCHITECTURE.md](../architecture/06_COMPILER_ARCHITECTURE.md) —
  how the compiler itself is put together, if you want to modify it.
