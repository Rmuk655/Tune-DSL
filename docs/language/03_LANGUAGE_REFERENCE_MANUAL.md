# 3. Tune DSL Language Reference Manual

> This file is the normative baseline for Tune v1. It must stay in
> sync with [00_WHITEPAPER.md](00_WHITEPAPER.md)'s design principles
> and with [05_LANGUAGE_EVOLUTION.md](05_LANGUAGE_EVOLUTION.md)'s frozen
> scope boundary. A behavior change to the parser or semantic analyzer
> should be reflected here.

## 3.0 Statement Quick Reference

| Statement | Where | Meaning |
|---|---|---|
| [`tempo` (3.3)](#33-top-level-statements) | top level | global BPM (default 120) |
| [`instrument` (3.3)](#33-top-level-statements) | top level | name a waveform, optional envelope override |
| [`let` (3.3)](#33-top-level-statements) | top level | compile-time constant |
| [`pattern` (3.3)](#33-top-level-statements) | top level | named sequence of pattern-body statements |
| [`play` (3.3)](#33-top-level-statements) | top level | schedule a pattern on an instrument, from beat 0 |
| [`effect` (3.3)](#33-top-level-statements) | top level | append to the global post-processing chain |
| [`note` (3.5)](#35-pattern-body-statements) | pattern body | one pitch for a duration |
| [`chord` (3.5)](#35-pattern-body-statements) | pattern body | several pitches, same start/duration |
| [`rest` (3.5)](#35-pattern-body-statements) | pattern body | silence for a duration |
| [`slide` (3.5)](#35-pattern-body-statements) | pattern body | glide from the previous pitch to a new one |
| [`strum` (3.5)](#35-pattern-body-statements) | pattern body | chord with staggered onsets |
| [`repeat` (3.5)](#35-pattern-body-statements) | pattern body | unroll a body N times |

## 3.1 Lexical Structure

**Whitespace/comments.** Spaces, tabs, `\r` are insignificant between
tokens. `#` starts a line comment. Newlines are significant — they are
emitted as explicit `NEWLINE` tokens and terminate most statements (a
statement may also legally end right before `EOF` or a closing `}`
with no `NEWLINE` required, so `pattern m { note C4 : 1/4 }` is legal
on one line).

**Identifiers.** `[A-Za-z_][A-Za-z0-9_]*`, except where the same text
also matches the pitch pattern below, in which case it lexes as
`PITCH` instead.

**Pitch literals.** One letter `A`-`G`, optionally `s` (sharp) or `b`
(flat), followed by exactly one octave digit, with no further
alphanumeric/`_` character immediately after: `C4`, `Cs4`, `Bb3`,
`Ds5`. (This `s`/`b` spelling is specific to Tune source pitch
literals — chord *symbols* in chord sheets use ordinary `#`/`b`
notation instead; see §6.2, a separate mini-syntax resolved before any
Tune source is generated.)

**Numbers.** `INT ::= [0-9]+`. `FLOAT ::= [0-9]+ "." [0-9]+` (a digit
must follow the `.`).

**Keywords** (reserved):
```
tempo  instrument  pattern  note  chord  rest  repeat
play   let          effect   slide  strum  envelope
```

**Symbols:** `{ } [ ] ( ) : , / + - * = @`

## 3.2 Grammar

```text
program        := stmt*
stmt           := tempo_stmt | instrument_decl | let_stmt
                | pattern_decl | play_stmt | effect_stmt | NEWLINE

tempo_stmt     := "tempo" expr NEWLINE
instrument_decl:= "instrument" IDENT "=" IDENT ["envelope" expr expr] NEWLINE
let_stmt       := "let" IDENT "=" expr NEWLINE
pattern_decl   := "pattern" IDENT "{" NEWLINE* pattern_body "}" NEWLINE
play_stmt      := "play" IDENT IDENT NEWLINE
effect_stmt    := "effect" IDENT expr*  NEWLINE

pattern_body   := pattern_stmt*
pattern_stmt   := note_stmt | chord_stmt | rest_stmt | repeat_stmt
                | slide_stmt | strum_stmt

note_stmt      := "note" PITCH ":" expr ["@" expr] NEWLINE
chord_stmt     := "chord" "[" PITCH ("," PITCH)* "]" ":" expr ["@" expr] NEWLINE
rest_stmt      := "rest" ":" expr NEWLINE
slide_stmt     := "slide" PITCH ":" expr ["@" expr] NEWLINE
strum_stmt     := "strum" "[" PITCH ("," PITCH)* "]" ":" expr
                    [IDENT("delay") expr] ["@" expr] NEWLINE
repeat_stmt    := "repeat" expr "{" NEWLINE* pattern_body "}" NEWLINE

expr           := term (("+"|"-") term)*
term           := factor (("*"|"/") factor)*
factor         := "-" factor | INT | FLOAT | IDENT | "(" expr ")"
```

Notes:

- `/` is purely arithmetic division to the parser; the "duration in
  beats" reading is a semantic convention, not a separate grammar rule.
- `strum`'s `delay` clause is a *contextual* identifier — the parser
  matches an `IDENT` token whose text is `"delay"`, not a reserved
  keyword.
- `effect` statements may appear anywhere among top-level statements;
  they apply to the whole final mix in declaration order regardless of
  where they're written relative to `instrument`/`pattern`/`play`.

## 3.3 Top-Level Statements

### `tempo <expr>`
Global BPM (1 beat = 1 quarter note). Must evaluate `> 0`. Defaults to
**120** if never declared.

### `instrument <name> = <waveform> [envelope <attack> <release>]`
`<waveform>` is one of `sine, square, saw, triangle, pulse, noise`.
`attack`/`release` (seconds, each `>= 0`) override the default 5ms
linear fade-in/out for notes played by this instrument. **Only the
Python backend renders a custom envelope** — see §5. Instrument names
must be unique.

### `let <name> = <expr>`
A compile-time constant, fully resolved during semantic analysis. Must
be declared before any expression that references it. Names must be
unique. There is no runtime mutation — `let` is not a variable in the
imperative sense.

### `pattern <name> { ... }`
A named sequence of pattern-body statements (§3.5). Inert until
referenced by `play`; an unused `pattern` is not an error. Names must
be unique.

### `play <instrument> <pattern>`
Schedules `pattern` on `instrument`, **starting at beat 0**. Multiple
`play` statements overlap/layer rather than concatenate. Both names
must already be declared.

### `effect <name> <args...>`
Appends to the global effect chain, applied to the entire mixed buffer,
in declaration order, before final peak normalization:

| Effect | Args | Meaning |
|---|---|---|
| `lowpass` | 1 | cutoff Hz — one-pole IIR low-pass |
| `highpass` | 1 | cutoff Hz — one-pole IIR high-pass |
| `distortion` | 1 | drive — tanh soft-clip, peak-preserving |
| `tremolo` | 2 | rate Hz, depth 0-1 — sine-LFO amplitude modulation |
| `delay` | 2 | time sec, feedback 0-1 — feedback delay line |

There is no per-instrument or per-pattern effect scoping.

## 3.4 Expressions

Standard precedence: `* /` bind tighter than `+ -`; unary `-` binds
tightest. All values are floats (ints coerce). Division by zero is a
semantic error. There is no boolean, string, or comparison support —
expressions exist only to compute numeric durations, tempos, effect
parameters, and `let` constants.

```tune
let base = 4
note C4 : 1 / base          # 0.25 beats
note C4 : (1 + 1) / 8       # 0.25 beats, different expression, same value
```

## 3.5 Pattern-Body Statements

### `note <pitch> : <duration> [@ <velocity>]`
`duration` must be `> 0`. `velocity` defaults to `1.0`, must be `>= 0`.
**A velocity-exactly-0 event is compiled away entirely** (dead-code
eliminated — it still advances the pattern's timeline, but is never
synthesized on any backend; see
[../architecture/DECISIONS.md](../architecture/DECISIONS.md)).

### `chord [<pitch>, ...] : <duration> [@ <velocity>]`
Two or more pitches, same start beat, same duration/velocity.

### `rest : <duration>`
Advances the timeline with no sound. No velocity clause.

### `slide <pitch> : <duration> [@ <velocity>]`
A linear frequency glide from the most recently emitted pitched event
**in the same pattern** (tracked through `repeat` unrolling) to
`<pitch>`. Requires a preceding pitched event — using `slide` first in
a pattern is a semantic error. Phase is computed as the true
time-integral of the linearly-ramping frequency, not `freq(t)*t`, so
the glide doesn't click. **Python backend only** — see §5.

### `strum [<pitch>, ...] : <duration> [delay <seconds>] [@ <velocity>]`
Like `chord`, but each pitch starts `delay` seconds after the previous
one (default `0.02`s, converted to beats via the current tempo). The
pattern's timeline still only advances by `duration` beats — later
notes in the strum may ring past that, matching a real strum's tail.

### `repeat <count> { ... }`
Unrolls its body `count` times (must evaluate to a non-negative
integer), with the timeline and `slide`'s "last pitch" state continuing
across iterations. Nests freely.

## 3.6 Pitch Names and Frequency

`<letter>[s|b]<octave>` under 12-tone equal temperament, A4 = 440Hz:

```
MIDI note number = (octave + 1) * 12 + semitone_within_octave(pitch_class)
freq_hz = 440.0 * 2 ^ ((midi - 69) / 12)
```

`Cs4`/`Db4`, `Ds4`/`Eb4`, `Fs4`/`Gb4`, `Gs4`/`Ab4`, `As4`/`Bb4` are
enharmonic pairs mapping to the same frequency. The octave increments
at `C` (`B3` is just below `C4`).

## 3.7 Semantic Rules Summary

- Every expression is fully constant-folded during semantic analysis;
  no backend ever evaluates an expression.
- `tempo` defaults to 120 if never declared.
- Instrument/pattern/`let` names must each be unique; referencing an
  undeclared one is an error, as is `play`ing an undeclared instrument
  or pattern.
- A `pattern` is only flattened into concrete events if referenced by
  at least one `play`.
- A program with zero `play` statements still compiles, with a warning,
  producing silence.

## 3.8 Backend Feature Matrix

All three backends consume the same flattened `SemanticResult` (see
[../architecture/INTERFACES.md](../architecture/INTERFACES.md)); the
front end is entirely backend-agnostic. Select with
`--backend {python,cpp,mlir}` (default `python`).

| Feature | `python` | `cpp` | `mlir` |
|---|:---:|:---:|:---:|
| All 6 waveforms, velocity, all 5 effects, `strum` | ✅ | ✅ | ✅ |
| `slide` | ✅ | ❌ hard error | ❌ hard error |
| Per-instrument `envelope` | ✅ | ❌ hard error | ❌ hard error |
| External toolchain | none (numpy only) | `g++` | `mlir-opt-19`, `mlir-translate-19`, `llc-19`, `gcc` |

`cpp`/`mlir` raise a clear, actionable error (rather than silently
dropping the feature) if the source uses `slide` or a custom
`envelope` — see
[../architecture/DECISIONS.md](../architecture/DECISIONS.md).

## 3.9 MIDI Export

`--export-midi <path>.mid` (available regardless of `--backend`,
always derived from the semantic result rather than backend-specific
rendering) writes a Format-1 Standard MIDI File: one track per `play`
statement, PPQ 480, tempo meta-event on the first track only.
**`effect` statements are not exported** — MIDI represents notes, not
audio signal processing; this is a property of the MIDI format, not an
exporter limitation. See
[../architecture/06_COMPILER_ARCHITECTURE.md §5](../architecture/06_COMPILER_ARCHITECTURE.md)
for the byte-level writer details.

## 3.10 Chord Sheets

A separate, higher-level, whitespace-delimited mini-format (`.guitar`,
`.bass`, `.keyboard`, ...) for chord progressions, converted to Tune
source by `chordsheet.py`. A file:

```
# comments start with #
tempo 96
beats_per_chord 4

C G Am F
C G F C:2 Am:2
```

- `tempo <bpm>` — optional.
- `beats_per_chord <n>` — optional, default `4`.
- `C:2` — this chord gets 2 beats instead of the default.
- `C*2` — repeats this chord for 2 full bars.

**Chord symbols** (`chord_theory.py`) use standard notation: root
`A`-`G` with optional `#`/`b`, optional quality suffix, optional
slash-bass (`C/E`). Supported qualities: `(none)/maj, m/min, 7, maj7/M7,
m7/min7, sus2, sus4, dim, dim7, aug, 5, 6, m6, 9, add9`.

**Instrument extensions** (`INSTRUMENT_DEFAULTS`) map a file extension
to a waveform, base octave, and whether only the chord's root note is
played:

| Ext | Waveform | Base octave | Root-only |
|---|---|---|:---:|
| `.guitar` | pulse | 3 | |
| `.keyboard`/`.piano` | sine | 4 | |
| `.veena`/`.sitar` | saw | 4 | |
| `.violin`/`.sarangi` | sine | 4 | |
| `.flute` | triangle | 5 | |
| `.mandolin` | pulse | 4 | |
| `.bass` | square | 2 | ✅ |
| `.harmonium` | triangle | 3 | |
| `.santoor` | pulse | 5 | |
| `.shehnai` | square | 5 | |
| `.synth` | saw | 4 | |
| `.tabla` | noise | 2 | ✅ |

**Honest scope note, stated directly by the module itself:** a chord
symbol carries harmony, not rhythm, tempo, or a specific voicing — the
user supplies tempo and per-chord durations by ear. This format does
not attempt physical-modeling synthesis of any real instrument's
timbre; each preset is a deliberate approximation using Tune's existing
6-waveform palette.

`chordsheet_cli.py` compiles one or more chord-sheet files (each
becoming its own uniquely-named instrument/pattern pair, layered
together) with the same `--backend`/`--export-midi`/`-o` flags as
`tune.py`, plus `--to-tune` to print the generated Tune source without
compiling it.
