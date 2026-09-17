# 1. Introduction

## 1.1 Motivation

Music notation is already a compact, structured, mostly-declarative
format: a tempo, a set of voices, and — per voice — a sequence of
pitched or silent events with durations. That structure maps cleanly
onto a small compiler: a lexer/parser for the notation, a semantic pass
that resolves all the arithmetic (note durations are naturally written
as fractions, like `1/4`), and a backend that turns the result into
actual samples.

Tune DSL takes that mapping literally. A `.tune` file is not a
scripting language for controlling a synthesizer at runtime — it's a
**score**, compiled once into a fixed list of timed events, then
rendered to a WAV file.

## 1.2 Project Objective

Implement a complete, small compiler:

```text
Tune source (.tune)
 -> Lexer -> Parser -> AST
 -> Semantic Analysis (constant folding + event flattening)
 -> SemanticResult (flat note events + effect chain)
 -> Synthesis backend (Python / C++ / MLIR)
 -> .wav (and optionally .mid)
```

...plus two things worth calling out as objectives in their own right,
not afterthoughts:

- **Backend redundancy as a correctness tool.** Three independent
  synthesis implementations exist specifically so they can be
  numerically diffed against each other. A backend bug that compiles
  and runs but produces subtly wrong audio is exactly the kind of bug
  that's easy to miss with only one implementation.
- **A real, standard-dialects MLIR backend**, not a toy — building a
  usable MLIR pipeline (`mlir-opt` → `mlir-translate` → `llc` → link)
  for an audio DSL is itself most of the point of that backend's
  existence.

## 1.3 Why a Domain-Specific Language?

You could write "play a C major arpeggio for two beats" as a general-
purpose-language function call with a list of frequencies and
durations. Tune instead makes music concepts first-class syntax:
`note`, `chord`, `rest`, `pattern`, `play`. The payoff of narrowing the
language this much:

- Durations are ordinary arithmetic (`1/4`, `(1+1)/8`) instead of
  magic numbers or an enum of note-length constants.
- A pattern reads the way sheet music reads — top to bottom, one event
  per line — instead of as a data structure being built up.
- The compiler can enforce music-specific invariants at compile time
  (e.g. "a `slide` needs a preceding pitched note to glide from") that
  would just be runtime assumptions in a general-purpose host language.

The tradeoff, accepted deliberately: Tune has no loops-over-data,
no conditionals, no functions with parameters, and no runtime state at
all beyond `repeat`'s fixed unrolling. It is not meant to scale to
"generative" or parametric composition — see
[05_LANGUAGE_EVOLUTION.md](../language/05_LANGUAGE_EVOLUTION.md) for
what a v2 might add.

## 1.4 Main Contributions

- A complete frontend: hand-written lexer, recursive-descent parser,
  and a semantic analysis pass that fully constant-folds every
  expression (no runtime variables exist in Tune v1).
- A flattening pass that turns nested `pattern`/`repeat` structure into
  a flat list of absolutely-timed `NoteEvent`s — the single
  representation every backend consumes.
- Three synthesis backends sharing that one representation:
  - `reference.py` — a NumPy implementation treated as ground truth.
  - `codegen.py` — generates a self-contained, auto-vectorizing C++
    program and compiles/runs it with `g++`.
  - `codegen_mlir.py` — generates a small, generic, reusable MLIR
    function library (real runtime dispatch via `scf.index_switch`,
    not per-event specialized code) and lowers it through
    `mlir-opt-19` → `mlir-translate-19` → `llc-19` → `gcc`.
- One dead-code-elimination pass, applied at the DSL semantic level: a
  note/chord/slide with velocity exactly 0 contributes nothing to any
  backend's mix and is provably safe to elide — see
  [DECISIONS.md](../architecture/DECISIONS.md).
- A hand-rolled WAV writer and a hand-rolled Standard MIDI File writer
  (no audio/MIDI library dependency for either writer).
- A chord-theory module (`chord_theory.py`) and a chord-sheet compiler
  (`chordsheet.py` / `chordsheet_cli.py`) that turn plain chord
  progressions into layered, multi-instrument Tune programs.
- A Flask web GUI that is a thin layer over the exact same compiler
  modules the CLI uses.
- A 242-test `pytest` suite (232 passing, 19 skipped in an environment
  without the MLIR 19 toolchain installed — see
  [TEST_MATRIX.md](../testing/TEST_MATRIX.md)), including sample-level
  numeric diffs between backends for every waveform and every effect.

## 1.5 Scope

**In scope (implemented):** tempo; 6 waveforms; `note`/`chord`/`rest`/
`repeat`/`slide`/`strum`; velocity; per-instrument envelope overrides;
5 global audio effects; `let` compile-time constants; WAV rendering on
three backends; MIDI export; a chord-sheet mini-language covering 16
instrument presets; a web GUI.

**Explicitly out of scope for v1** (see
[05_LANGUAGE_EVOLUTION.md](../language/05_LANGUAGE_EVOLUTION.md) for the
full, frozen boundary list): runtime variables/loops over data,
conditionals, functions/parameters, multiple simultaneous tempos or
tempo changes mid-song, per-`play` effect scoping, any notion of stereo
panning, and true physical-modeling instrument timbres (the
chord-sheet's instrument presets are an honest, stated approximation
using the language's existing 6 waveforms — see
[03_LANGUAGE_REFERENCE_MANUAL.md §6](../language/03_LANGUAGE_REFERENCE_MANUAL.md)).

## 1.6 Known Limitations

Two backend asymmetries are worth calling out up front (the full list
lives in [KNOWN_BUGS.md](../testing/KNOWN_BUGS.md)):

- **`slide` (frequency glide) and per-instrument `envelope` overrides
  only render on the Python backend.** The C++ and MLIR backends detect
  either feature in the semantic result and fail with a clear,
  actionable error (`CppBackendError` / `MlirBackendError`) rather than
  silently ignoring them and producing audio that doesn't match what
  the Python backend would render for the same source.
- **The MLIR backend needs a real, version-pinned toolchain**
  (`mlir-opt-19`, `mlir-translate-19`, `llc-19`, `gcc`) that isn't
  bundled with the project and may not be present on a given machine —
  the test suite and CLI both detect its absence and skip/fail cleanly
  rather than crashing.

## 1.7 Positioning

Tune DSL doesn't claim that music-as-code or programmatic audio
synthesis is a new idea — Sonic Pi, ChucK, Csound, Tidal, and plain
MIDI sequencing all cover overlapping ground, with far more maturity.
This project's actual contribution is narrower and more concrete: a
complete, small, well-tested compiler pipeline built from scratch —
including a real (if intentionally small) MLIR backend — as a personal
exercise in compiler construction, with music as the domain because
it gives immediate, checkable (audible, and numerically diffable)
feedback on whether the compiler did the right thing.
