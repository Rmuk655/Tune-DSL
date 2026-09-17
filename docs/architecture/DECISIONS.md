# Tune DSL Architecture Decision Records

> Each record: Problem, Options, Decision, Rationale, Affected modules,
> Consequences. Language-level decisions (what the syntax can express)
> are covered by [../language/00_WHITEPAPER.md](../language/00_WHITEPAPER.md)
> and frozen by [../language/05_LANGUAGE_EVOLUTION.md](../language/05_LANGUAGE_EVOLUTION.md);
> these are *compiler-implementation* decisions.

---

## ARCH-001 — Round durations in Python, not C++

**Problem.** Converting a beat-based duration to a sample count
requires rounding a float to an integer. If both the Python reference
backend and the generated C++ backend each do this rounding
independently, they can disagree.

**Options.** (a) Let each backend round independently, in its own
language's native way; (b) round once, in Python, during code
generation, and bake the resulting integer sample counts into the
generated C++ source as literals.

**Decision.** (b).

**Rationale.** Python's `round()` is round-half-to-even; C++'s
`llround()` is round-half-away-from-zero. Musical durations land on
exact `.5`-sample boundaries often enough that this difference is not
academic — it can shift a note's start sample by one between backends,
which is audible as a shifted waveform phase for that note's entire
duration. Removing the second rounding decision entirely (there's
nothing left for the generated C++ to round) removes the disagreement
at the source, rather than trying to make two independent roundings
agree.

**Affected.** `src/codegen.py` (and, by the same reasoning,
`src/codegen_mlir.py`, which also precomputes sample counts in Python).

**Consequences.** The generated C++/MLIR source contains precomputed
integer literals rather than runtime duration→sample-count arithmetic.
This is slightly less "generic" generated code, but it's what makes the
backends diffable sample-for-sample against `reference.py` at all.

---

## ARCH-002 — `-ffast-math` for the C++ hot loop

**Problem.** The C++ backend's per-sample synthesis loop needs to
auto-vectorize to be worth generating C++ for at all. `-ffast-math`
enables that, but it also permits floating-point reassociation.

**Options.** (a) Compile without `-ffast-math`, keeping strict IEEE
semantics but losing auto-vectorization; (b) compile with
`-ffast-math`, accepting a documented, rare correctness tradeoff.

**Decision.** (b), documented directly in the generated file's own
header comment.

**Rationale.** The whole point of the C++ backend is speed via
vectorization; a backend that doesn't vectorize its hot loop has little
reason to exist alongside the Python reference. The tradeoff is small
and specific: reassociation can, in rare cases, flip a comparison at an
exact phase tie — a single, inaudible (~22µs) event — not a systematic
divergence.

**Affected.** `src/codegen.py`'s compile invocation and its generated
header comment.

**Consequences.** If bit-exact determinism against the Python reference
ever matters more than throughput for some future use case, compiling
with `-fno-math-errno` alone (instead of `-ffast-math`) is documented
as the alternative — at the cost of losing auto-vectorization.

---

## ARCH-003 — `std::fmod` avoided for phase wrapping

**Problem.** Wrapping a running phase value into `[0,1)` can be written
as `std::fmod(raw, 1.0)` or as `raw - std::floor(raw)`.

**Decision.** `raw - std::floor(raw)`.

**Rationale.** `std::fmod` has errno side effects (for edge-case
inputs like `fmod(x, 0)`), and compilers generally can't auto-vectorize
a loop containing a call that might set `errno` — verified empirically
during backend development. `std::floor` has no such side effect and
vectorizes cleanly.

**Affected.** `src/codegen.py`'s generated per-sample loop.

**Consequences.** None functionally (both expressions are mathematically
equivalent for the phase ranges this loop produces); purely a
vectorization enabler.

---

## ARCH-004 — Hard error, not silent feature drop, for backend gaps

**Problem.** `slide` and per-instrument `envelope` overrides are
implemented only on the Python backend. What should `--backend cpp`/
`mlir` do with a source file that uses either?

**Options.** (a) Silently ignore the feature (e.g. render a `slide` as
a plain `note` with no glide); (b) fail immediately, before generating
any code, with a message naming the exact unsupported feature and
pointing at `--backend python`.

**Decision.** (b).

**Rationale.** Silently dropping a feature would produce audio that
compiles and runs successfully but doesn't match what the same source
renders as on the Python backend — the worst kind of bug, since nothing
about the output *looks* wrong until it's compared closely. A loud,
specific, actionable error was judged strictly better than a backend
that's quietly wrong for a subset of otherwise-valid programs.

**Affected.** `src/codegen.py` (`CppBackendError`), `src/codegen_mlir.py`
(`MlirBackendError`).

**Consequences.** These two features are effectively Python-backend-only
in practice, tracked explicitly as a known gap rather than a silent one
— see
[../language/05_LANGUAGE_EVOLUTION.md §5.4](../language/05_LANGUAGE_EVOLUTION.md#54-known-backend-asymmetry-not-a-language-boundary).

---

## ARCH-005 — One flattened event list per pattern *name*, not per (instrument, pattern) pair

**Problem.** A `pattern`'s flattening (resolving pitches, applying an
instrument's waveform/envelope, unrolling `repeat`) depends on which
instrument plays it. Should the flattened result be cached by pattern
name alone, or by the `(instrument, pattern)` pair?

**Decision.** By pattern name alone — the first `play` statement that
references a given pattern determines the flattening used for it; a
later `play` of the *same* pattern name (even with a different
instrument) reuses that cached result rather than re-flattening.

**Rationale.** This was the simpler cache key to implement, and no
current example or test plays one pattern with two different
instruments, so the distinction never surfaces in practice.

**Affected.** `src/semantic.py`'s pattern-flattening cache.

**Consequences.** If a future program does `play lead melody` and
`play pad melody`, both would (incorrectly) use `lead`'s
waveform/envelope for `melody`. This is a known, documented sharp edge
— see
[../ProjectMgmt/09_CONCLUSIONS_LESSONS_LEARNED.md §9.3](../ProjectMgmt/09_CONCLUSIONS_LESSONS_LEARNED.md#93-what-would-be-done-differently)
— not a silent miscompilation of anything currently tested or
documented as supported.

---

## ARCH-006 — Velocity-0 dead-code elimination

**Problem.** Should a `note`/`chord`/`slide` event with `velocity = 0`
be synthesized at all?

**Decision.** No — it's elided during semantic analysis (counted in
`SemanticResult.dce_eliminated`), while its timing side effects (beat
advancement, "last pitched frequency" for a following `slide`) are
still applied exactly as if it had been kept.

**Rationale.** A velocity-0 event contributes exactly zero to every
backend's summed mix — this is provably safe, the same reasoning a
general-purpose compiler applies to eliminating a dead store. It's a
genuine (if narrow) optimization rather than just parsing/codegen work.

**Affected.** `src/semantic.py`'s pattern-flattening pass.

**Consequences.** None observable — output is bit-identical to keeping
the event and multiplying by zero, just without doing the multiplying.

---

## ARCH-007 — No custom MLIR dialect

**Problem.** Build a `tune` MLIR dialect for these operations, or lower
directly to existing standard dialects?

**Decision.** Lower directly to `func`/`arith`/`scf`/`memref`/`math`/
`index`.

**Rationale.** A custom dialect needs TableGen op definitions and a
custom conversion pass — real, multi-day infrastructure work with no
payoff for what this project's operations actually need to express (a
handful of parameterized synthesis/effect functions). Nothing in the
frozen v1 feature set needs a high-level op to survive lowering.

**Affected.** `src/codegen_mlir.py`.

**Consequences.** Simpler backend to build and maintain; a dialect
remains an option later if a future pass ever needs to preserve a
high-level pattern through lowering, but nothing currently requires it.

---

## ARCH-008 — Generic MLIR functions, called per event, not per-event specialized code

**Problem.** For N note events, generate N independent, specialized
blocks of IR (each with its constants baked in), or one small,
parameterized function library called N times?

**Decision.** The latter: one `@synth_event` function (with a genuine
runtime `scf.index_switch` for waveform dispatch) and one `@apply_*`
function per effect, called once per event/effect from a driving
function.

**Rationale.** Per-event specialized IR would duplicate the same
arithmetic N times and would make waveform dispatch a compile-time
choice baked separately into each call site — the opposite of what
makes this backend interesting to have built at all (see
[../ProjectMgmt/01_INTRODUCTION.md §1.2](../ProjectMgmt/01_INTRODUCTION.md#12-project-objective)).
A shared, parameterized library with real runtime dispatch is *more*
general than the C++ backend's compile-time template dispatch, not
less — a deliberate point of differentiation between the two backends
rather than a redundant reimplementation.

**Affected.** `src/codegen_mlir.py`.

**Consequences.** Slightly more IR-level indirection (an indirect-ish
call through a switch) per event than a fully unrolled specialization
would have; judged an acceptable cost for the design goal above.

---

## ARCH-009 — MLIR function library verified standalone before integration

**Problem.** How to gain confidence that a hand-written MLIR function
library is numerically correct, given the multi-stage external
toolchain (`mlir-opt-19` → `mlir-translate-19` → `llc-19` → `gcc`)
between writing the IR and hearing the result?

**Decision.** Build and verify each piece of the function library as a
standalone `.mlir` prototype first (`mlir_test/synth_event_prototype.mlir`,
`mlir_test/effects_prototype.mlir`, and intermediate artifacts from
running them through the real pipeline), numerically diffed against
`reference.py` one waveform and one effect at a time, *before*
embedding any of it into `codegen_mlir.py`'s generator.

**Rationale.** Debugging a full multi-event, multi-effect program
through an opaque four-stage external toolchain, all at once, makes it
very hard to localize a mismatch to a specific waveform or effect.
Isolating each piece first turns "the MLIR backend sounds wrong
somewhere" into a much smaller, addressable question.

**Affected.** `mlir_test/`, `src/codegen_mlir.py`.

**Consequences.** Slower initial development (each function verified
twice — once standalone, once integrated), but the integration step
itself landed correctly on the first pass as a result.

---

## ARCH-010 — Chord sheets state their own scope honestly

**Problem.** A chord-sheet file (`.guitar`, `.bass`, etc.) could be
presented as reproducing a real song's arrangement.

**Decision.** Document plainly, in the module itself, that a chord
symbol carries harmony only — not rhythm, tempo, or a specific
voicing — and that instrument-extension presets are simple waveform
approximations, not physical models of real instrument timbres.

**Rationale.** The format genuinely can't derive tempo or exact
voicings from chord names alone, and doesn't attempt real instrument
modeling. Overselling either would mislead a user about what the tool
actually does.

**Affected.** `src/chordsheet.py`'s module docstring;
[../language/03_LANGUAGE_REFERENCE_MANUAL.md §3.10](../language/03_LANGUAGE_REFERENCE_MANUAL.md#310-chord-sheets)
repeats this note where a user of the format will see it.

**Consequences.** None functional — purely a documentation-honesty
decision.
