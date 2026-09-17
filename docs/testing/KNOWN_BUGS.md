# Known Bugs and Limitations

## A note on how this file was produced

This document was written by reading the source and running the actual
test suite (`232 passed, 19 skipped` — see
[TEST_MATRIX.md](TEST_MATRIX.md)), not from a historical bug tracker —
none exists for this project. There are accordingly no dated,
numbered `BUG-XXX` entries here with a "reported by / fixed by" trail;
everything below is either a **known limitation by design** (stated
in the code itself) or a **known asymmetry** (a documented, detected
gap between backends). No open defect was found during this review.

## Known Limitations (by design, not bugs)

These are intentional v1 scope boundaries — see
[../language/05_LANGUAGE_EVOLUTION.md](../language/05_LANGUAGE_EVOLUTION.md)
for the full list and rationale. Listed here so they aren't mistaken
for defects:

- No runtime variables, loops-over-data, or conditionals — `let` is a
  compile-time constant and `repeat` unrolls at compile time.
- No functions or parameterized patterns — a `pattern` can't take
  arguments.
- No tempo changes mid-song — `tempo` is one global value.
- No per-instrument or per-pattern effect scoping — `effect` always
  applies to the whole final mix.
- No stereo/spatial audio — every backend renders mono.
- No physical-modeling instrument timbres, in the core language or in
  the chord-sheet instrument presets — both use a small, fixed set of
  basic waveforms as a stated, deliberate approximation.

## Known Backend Asymmetry (documented, detected, not silent)

- **`slide` (frequency glide) and per-instrument `envelope` overrides
  only render on `--backend python`.** `--backend cpp` and `--backend
  mlir` detect either feature in the semantic result and fail
  immediately with a specific, actionable error message — this is a
  deliberate hard-failure design (see
  [../architecture/DECISIONS.md, ARCH-004](../architecture/DECISIONS.md#arch-004-hard-error-not-silent-feature-drop-for-backend-gaps)),
  not an unnoticed gap. Porting both features to the other two backends
  is the most concrete outstanding implementation task — see
  [../language/05_LANGUAGE_EVOLUTION.md §5.4](../language/05_LANGUAGE_EVOLUTION.md#54-known-backend-asymmetry-not-a-language-boundary).
- **The MLIR backend requires a real, version-pinned external
  toolchain** (`mlir-opt-19`, `mlir-translate-19`, `llc-19`, `gcc`)
  that may simply not be installed on a given machine. Both the CLI and
  the test suite detect this and fail/skip cleanly with a named-tool
  error rather than crashing — see
  [../development/DEPENDENCIES.md](../development/DEPENDENCIES.md) and
  [TEST_MATRIX.md](TEST_MATRIX.md#skip-conditions).

## A Documented Sharp Edge (not currently triggerable by any example)

- **Pattern-flattening cache is keyed by pattern name alone, not by
  `(instrument, pattern)`** (see
  [../architecture/DECISIONS.md, ARCH-005](../architecture/DECISIONS.md#arch-005-one-flattened-event-list-per-pattern-name-not-per-instrumentpattern-pair)).
  If a future program `play`s the *same* pattern name with two
  *different* instruments, both would use whichever instrument's
  waveform/envelope was resolved first, rather than each instrument
  rendering the pattern with its own settings. No shipped example or
  test currently does this, so it hasn't been observed as an actual
  wrong-output case — it's flagged here as a design constraint to be
  aware of before relying on that pattern.

## Format for Filing a Future Bug

If a real defect is found, the useful fields to capture (matching what
[TEST_MATRIX.md](TEST_MATRIX.md) already tracks per module) are:

```text
Title:
Phase:      lexer | parser | semantic | reference | codegen | codegen_mlir
            | midi_export | chord_theory | chordsheet | gui
Severity:   blocker | major | minor
Repro:      minimal .tune (or chord-sheet) source, or a failing test name
Expected:
Actual:
Status:     open | fixed
```

Once a real defect exists, add a regression test alongside the fix in
the matching file under `tests/` (see [TEST_MATRIX.md](TEST_MATRIX.md)
for which file owns which module) rather than only fixing the code.
