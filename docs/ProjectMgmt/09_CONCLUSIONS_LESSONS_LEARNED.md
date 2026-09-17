# 9. Conclusions and Lessons Learned

## 9.1 What Went Well

**Keeping one backend as "ground truth" paid for itself immediately.**
`reference.py` is deliberately the simplest-possible correct
implementation — plain NumPy, no cleverness, straightforward per-sample
math. Every other backend (`codegen.py`, `codegen_mlir.py`) exists to
be numerically diffed against it. This turned "does the C++ backend
work?" from a listening test into an assertion (`test_codegen.py`'s
`test_*_matches_python_reference` tests, `test_codegen_mlir.py`'s
equivalents) — a much cheaper and more reliable way to catch a backend
bug that compiles and runs but produces subtly wrong audio.

**Constant-folding everything up front simplified every backend.**
Because semantic analysis fully resolves `let` variables, arithmetic,
tempo, and every duration/velocity/effect argument down to plain floats
before any backend ever runs, none of the three backends need to
implement expression evaluation, variable scoping, or arithmetic at
all — they only ever consume a flat list of already-computed
`NoteEvent`s. This is a large chunk of "language" complexity that
simply doesn't exist on the far side of semantic analysis.

**One narrow, provably-safe DCE pass was worth having, even in a
project this size.** A velocity-0 event contributes exactly zero to
every backend's mix, so eliding its synthesis is observably identical
to keeping it — the same reasoning a real compiler applies to a dead
store. It's a small thing (`SemanticResult.dce_eliminated`), but it's a
genuine, if minor, compiler optimization, not just parsing/codegen.

## 9.2 What Was Harder Than Expected

**Making two independently-written backends agree bit-for-bit is
harder than making them agree "closely enough."** The project's own
code comments record the two concrete traps found:

- Python's `round()` is round-half-to-even; C++'s `llround()` is
  round-half-away-from-zero. Musical durations land on exact
  `.5`-sample boundaries often enough that letting each backend round
  independently would occasionally shift a note's start sample by one
  — audible as a shifted waveform phase for that note's whole duration.
  The fix was to stop giving C++ a rounding decision to make at all:
  round once, in Python, and bake the resulting integers into the
  generated source.
- `-ffast-math` (needed for the hot per-sample loop to auto-vectorize)
  permits floating-point reassociation, which can in rare cases flip a
  comparison at an exact phase tie. This is real, documented, and
  accepted as a tradeoff (see
  [DECISIONS.md, ARCH-002](../architecture/DECISIONS.md#arch-002-ffast-math-for-the-c-hot-loop))
  rather than papered over.

**A "generic" MLIR backend is a genuinely different design problem from
a "fast" one.** The natural first instinct for compiling N note events
is to unroll one specialized, constant-baked block of IR per event.
`codegen_mlir.py` deliberately does the opposite: a small, fixed
library of parameterized functions (`@synth_event`, one `@apply_*` per
effect), called once per event/effect, with waveform dispatch as a
genuine runtime `scf.index_switch` inside the IR. Verifying that
library's pieces independently first — as standalone `.mlir` files in
`mlir_test/`, compiled through the full `mlir-opt` → `mlir-translate` →
`llc` pipeline and numerically diffed against `reference.py` one
waveform and one effect at a time — before wiring them into the full
generator was what made the eventual integration land correctly on the
first pass; skipping that step and debugging the whole pipeline at once
would have made isolating a mismatch far harder.

**"Honest scope" is a real design decision, not just a disclaimer.**
The chord-sheet format could have quietly implied it reproduces a
specific reference recording. It doesn't, and the module docstring says
so explicitly: a chord symbol carries harmony, not rhythm or timbre,
and the per-instrument waveform presets are a deliberate approximation
using Tune's existing 6-waveform palette, not physical-modeling
synthesis. Writing that down where a user of the format will actually
see it (the module docstring, quoted in
[03_LANGUAGE_REFERENCE_MANUAL.md §6](../language/03_LANGUAGE_REFERENCE_MANUAL.md))
was a deliberate choice to avoid overselling what a fairly small piece
of code actually does.

## 9.3 What Would Be Done Differently

- **Backend feature parity should probably have been designed in from
  the start**, rather than `slide` and per-instrument `envelope`
  landing only in the Python backend and being retrofitted as "hard
  error on the other two backends." The hard-error behavior is the
  right choice given where things ended up (silently producing wrong
  audio would be much worse), but designing the semantic representation
  so every backend could express these two features from day one would
  have avoided the asymmetry entirely.
- **A single `(instrument, pattern)` → events cache keyed only by
  pattern name** means that if the *same* pattern is `play`ed by two
  *different* instruments, only the first instrument's waveform/
  envelope is actually used for both — see
  [DECISIONS.md, ARCH-005](../architecture/DECISIONS.md#arch-005-one-flattened-event-list-per-pattern-name-not-per-instrumentpattern-pair).
  This is documented and doesn't affect any current example (nothing
  plays one pattern with two instruments), but a cache keyed on the
  `(instrument, pattern)` pair instead of just `pattern` would remove
  the sharp edge entirely and is the more correct design.

## 9.4 Overall

The project's central bet — that keeping three independently-built
synthesis backends in numeric lockstep is worth the extra engineering
cost — paid off specifically because it converted "does this sound
right" into "does this match, sample for sample, within a documented
tolerance," which is testable in CI rather than only testable by ear.
That discipline is the main thing worth carrying into any future
extension of this project.
