# 5. Tune DSL — Scope Freeze and Evolution

## 5.1 Purpose

This file records what Tune v1 deliberately does and does not include,
so a gap is legible as "out of scope by design" rather than filed as a
bug. See [../testing/KNOWN_BUGS.md](../testing/KNOWN_BUGS.md) for the
distinction in practice.

## 5.2 v1 — Frozen Scope

Everything in
[03_LANGUAGE_REFERENCE_MANUAL.md](03_LANGUAGE_REFERENCE_MANUAL.md) is
the frozen v1 language: `tempo`, `instrument` (+ optional `envelope`),
`let`, `pattern`, `play`, `effect`, and the six pattern-body statements
(`note`, `chord`, `rest`, `slide`, `strum`, `repeat`), plus the
chord-sheet companion format and MIDI export.

## 5.3 Explicitly Out of Scope for v1

- **No runtime variables, loops-over-data, or conditionals.** `let` is
  a compile-time constant; `repeat` unrolls at compile time. There is
  no way for a `.tune` program's behavior to depend on anything not
  known when it's compiled.
- **No functions or parameterized patterns.** A `pattern` cannot take
  arguments; there's no way to write one melodic shape and instantiate
  it transposed/scaled without literally rewriting it.
- **No tempo changes mid-song.** `tempo` is a single global value for
  the whole program.
- **No per-instrument or per-pattern effect scoping.** `effect` always
  applies to the entire final mix.
- **No stereo/spatial audio.** Every backend renders mono.
- **No physical-modeling instrument timbres.** Both core Tune
  waveforms and the chord-sheet's instrument presets are simple,
  clearly-scoped approximations (6 basic waveforms), not simulations of
  how a real guitar/veena/tabla/etc. actually produces sound.
- **`slide` and per-instrument `envelope` are Python-backend-only.**
  This is a backend-completeness gap rather than a language-scope
  decision — see §5.4.

## 5.4 Known Backend Asymmetry (Not a Language Boundary)

Unlike the items in §5.3, `slide` and per-instrument `envelope` *are*
part of the frozen v1 language — they're just not yet implemented on
the C++ and MLIR backends. `codegen.py` and `codegen_mlir.py` detect
either feature in the semantic result and raise a clear,
backend-specific error rather than silently ignoring it (see
[../architecture/DECISIONS.md](../architecture/DECISIONS.md)). Porting
both to the other two backends is the most concrete, well-scoped v1.x
task this project has (no new syntax needed — matching behavior that
already exists and is already fully specified on the Python backend).

## 5.5 Likely v2 Candidates

None of these are committed or scheduled — they're the natural next
steps if the language were to grow:

- **Parameterized patterns / pattern transposition** — e.g. `pattern
  melody(shift) { ... }` or a `transpose <pattern> by <n>` construct,
  so one melodic shape can be reused at different pitches without
  copy-pasting it.
- **Per-`play` effect scoping** — letting one instrument's part run
  through its own effect chain instead of only a single global one.
- **Tempo changes mid-song** — a `tempo` statement inside a pattern
  rather than only at the top level, with a defined interaction with
  already-scheduled events.
- **Backend parity for `slide`/`envelope`** (§5.4) — the most concrete
  and lowest-risk of the candidates here, since it needs no new syntax.
- **Stereo panning** — a per-instrument or per-event pan value, which
  would touch every backend's mixing step.

## 5.6 Permanently Out of Scope (Not Just "Not Yet")

- **Physical-modeling synthesis of real instrument timbres.** This
  would be a fundamentally different (and much larger) project than a
  6-waveform synthesizer with a fixed effect chain; it's not a
  "someday" item for this codebase.
- **MIDI *input*, or any real-time/live-performance mode.** Tune is,
  by design, a batch compiler for a static score (see
  [00_WHITEPAPER.md §2](00_WHITEPAPER.md)) — real-time behavior is a
  different problem with a different architecture, not an extension of
  this one.
