# 12. Project FAQ and Design Defense

## 12.1 Format

A self-contained walkthrough for demonstrating the compiler: a working
example per backend, two failure examples, and answers to the design
questions most likely to come up. Useful for a live demo or for
re-orienting after time away from the code.

## 12.2 One-Sentence Pitch

"Tune DSL is a small music-notation language that compiles to real
audio through three independently implemented, numerically
cross-checked synthesis backends — a NumPy reference, a generated C++
program, and a generated MLIR pipeline through the real LLVM/MLIR
toolchain — plus MIDI export and a chord-progression compiler for
people who think in chords rather than notes."

## 12.3 Working Examples (Live Demo)

All three commands below are real, run through the actual `tune.py`
CLI, not a test harness.

```bash
# Python backend (default) — always available, supports every feature
python3 tune.py examples/extended_demo.tune
# wrote examples/extended_demo.wav (...s, tempo 100 bpm)

# C++ backend — requires g++
python3 tune.py examples/melody.tune --backend cpp
# wrote <n> samples, <t> sec

# MLIR backend — requires mlir-opt-19/mlir-translate-19/llc-19/gcc
python3 tune.py examples/melody.tune --backend mlir
```

A chord-progression example, showing the generated Tune source before
compiling it:

```bash
python3 chordsheet_cli.py examples/chordsheets/demo_song.guitar --to-tune
python3 chordsheet_cli.py examples/chordsheets/demo_song.guitar examples/chordsheets/demo_song.bass
# wrote demo_song.wav, guitar + bass layered
```

## 12.4 Failure Examples

**A syntax error** (missing newline between two statements — see
[03_LANGUAGE_REFERENCE_MANUAL.md §3.1](../language/03_LANGUAGE_REFERENCE_MANUAL.md)
on statement termination):

```tune
tempo 120 instrument lead = sine
```
```
parse error: ParseError at 1:11: expected NEWLINE, got INSTRUMENT ('instrument')
```

**A feature/backend mismatch** — `slide` on a backend that doesn't
support it:

```bash
python3 tune.py examples/slide_strum_demo.tune --backend cpp
```
```
error: the C++ backend does not yet support `slide` (frequency glide) -- use --backend python for programs that use slide
```

This is a deliberate hard failure, not a silent feature drop — see
[DECISIONS.md, ARCH-004](../architecture/DECISIONS.md#arch-004-hard-error-not-silent-feature-drop-for-backend-gaps).

## 12.5 Anticipated Questions

**Q: Why three backends instead of one good one?**
Because a single implementation can't catch its own bugs. Keeping
`reference.py` as ground truth and diffing `codegen.py`/
`codegen_mlir.py` against it, sample-for-sample, turns "does the fast
backend actually sound right" into an automated test
(`test_codegen.py`, `test_codegen_mlir.py`) instead of a listening
exercise.

**Q: Is the MLIR backend "real," or a wrapper around something else?**
It's real: it emits actual MLIR text using only standard dialects
(`func`, `arith`, `scf`, `memref`, `math`, `index` — no custom "Tune
dialect"), and shells out to the real `mlir-opt-19` → `mlir-translate-19`
→ `llc-19` → `gcc` pipeline. The generic function library it emits
(`@synth_event` with a genuine runtime `scf.index_switch` for waveform
dispatch, one `@apply_*` function per effect) was verified independently
first as standalone `.mlir` prototypes under `mlir_test/`, compiled
through that exact pipeline and diffed against `reference.py`, before
being embedded in `codegen_mlir.py`.

**Q: Why does `/` mean two different things (fractions of a beat,
ordinary division)?**
It doesn't — it means one thing (division) everywhere. `1/4` isn't a
special "duration literal" syntax; it's the same binary `/` operator
used anywhere else in an expression, which happens to evaluate to
`0.25`. Whether that float is later interpreted as "beats" or an
"effect argument" is entirely a semantic-analysis concern, not a
parser concern — see
[03_LANGUAGE_REFERENCE_MANUAL.md §3.2](../language/03_LANGUAGE_REFERENCE_MANUAL.md).

**Q: Why is there no runtime state — no variables that change, no
loops over data?**
Because nothing in the language needs it. Every `.tune` program is a
fixed, finite score known entirely at compile time; `repeat` unrolls at
compile time, and `let` is a named compile-time constant, not a mutable
variable. This is a scope decision, not an oversight — see
[05_LANGUAGE_EVOLUTION.md](../language/05_LANGUAGE_EVOLUTION.md) for
what a generative/parametric v2 extension would need to add.

**Q: Why do the C++ and MLIR backends reject `slide` and per-instrument
`envelope` instead of just ignoring them?**
Because silently ignoring a feature would produce audio that compiles
and runs but doesn't match what the same source renders as on the
Python backend — the worst kind of bug, since nothing about it looks
wrong until you listen closely or diff the output. An explicit,
actionable error (naming the exact unsupported feature and pointing at
`--backend python`) was judged strictly better than a backend that's
quietly wrong for a subset of valid programs.

**Q: Does the chord-sheet format reproduce a specific recording?**
No, and the code says so directly: a chord symbol carries harmony, not
rhythm or tempo or a specific voicing — the format asks the user to
supply beats-per-chord and tempo by ear. It also does not attempt
physical-modeling synthesis of any real instrument's timbre; each
instrument extension (`.guitar`, `.veena`, `.tabla`, ...) maps to one of
Tune's 6 existing waveforms as a deliberately honest approximation, not
a claim of realism. See
[03_LANGUAGE_REFERENCE_MANUAL.md §6](../language/03_LANGUAGE_REFERENCE_MANUAL.md).

**Q: What happens if I compile a program with no `play` statements?**
It succeeds, with a warning ("output will be silent") — an unused
`pattern` or a program that never plays anything is treated as valid
(if pointless) rather than an error.

**Q: How is `noise` deterministic if it's supposed to sound random?**
It's a fixed avalanche hash (`triple32`-style: XOR-shift/multiply
rounds with two specific 32-bit constants) of the *absolute sample
index*, not a seeded PRNG with internal state. Same index, same output,
every time, on every backend — which is exactly what's needed for the
three backends to be diffable against each other at all.

## 12.6 What's Genuinely Unfinished

Stated plainly, not hidden in a corner: `slide` and per-instrument
`envelope` overrides are Python-backend-only (§12.5 above explains why
this fails loudly rather than silently); the MLIR backend needs a real,
version-pinned external toolchain that may not be present on a given
machine (the test suite and CLI both detect this and skip/fail
cleanly — see [TEST_MATRIX.md](../testing/TEST_MATRIX.md)). Neither is
a silent correctness gap; both are documented, detected, and reported
clearly at the point they'd matter.
