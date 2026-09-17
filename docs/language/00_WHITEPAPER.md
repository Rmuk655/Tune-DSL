# 0. Tune DSL Whitepaper

## 1. Problem

Writing music programmatically usually means one of two extremes:
a general-purpose host language with an audio library bolted on (all
the expressive power of the host language, none of the domain
structure), or a fully graphical DAW (all the domain structure, none of
it as text you can diff, version, or generate). Tune sits deliberately
in between: a small, textual, declarative notation whose only job is
describing a score, compiled by a real (if small) pipeline down to
either PCM audio or MIDI.

## 2. Design Principles

1. **A `.tune` program is a score, not a script.** Nothing in the
   language can depend on anything decided at render time — no user
   input, no randomness with hidden state, no wall-clock behavior.
   Compile the same source twice and you get the same events every
   time.
2. **Everything resolvable at compile time is resolved at compile
   time.** `let`, tempo, every duration/velocity/effect argument, and
   `repeat` unrolling are all constant-folded during semantic analysis.
   No backend ever evaluates an expression — only a flat list of
   already-numeric `NoteEvent`s.
3. **One ground-truth backend, checked against by construction.**
   `reference.py` is written to be obviously, simply correct — not
   fast. Every other backend's job is to match it, and "matching" is
   measured numerically (sample-level diff), not by ear.
4. **A DSL's honesty matters as much as its power.** Where the language
   or a companion tool can't actually do what a user might assume (the
   chord-sheet format cannot infer a recording's tempo or exact
   voicings; the chord-sheet instrument presets are not physical models
   of real instruments), the documentation says so plainly rather than
   implying more than the code delivers.
5. **Prefer standard infrastructure over custom infrastructure.** The
   MLIR backend deliberately uses only stock MLIR dialects. Building a
   custom "Tune dialect" would mean TableGen op definitions and a
   custom conversion pass — real, multi-day engineering with no payoff
   for what v1 actually needs to express.

## 3. What a `.tune` Program Is

At the top level, a program declares:

- an optional **tempo** (defaults to 120 BPM if omitted),
- zero or more **instruments** (a name bound to one of 6 waveforms,
  plus an optional envelope override),
- zero or more **`let`** compile-time constants,
- zero or more **patterns** (named sequences of notes/chords/rests/
  slides/strums/repeats),
- zero or more **`play`** statements (which instrument performs which
  pattern — all starting at beat 0, layered together),
- zero or more **`effect`** statements (a global, ordered
  post-processing chain over the final mix).

See [03_LANGUAGE_REFERENCE_MANUAL.md](03_LANGUAGE_REFERENCE_MANUAL.md)
for the full, normative grammar.

## 4. Why These Particular Design Choices

**Why beats, not seconds, as the native duration unit?** Because that's
how music is actually written and read — a quarter note is "1 beat"
regardless of tempo, and changing the tempo should rescale a whole
song's timing without touching any pattern. Beats are converted to
seconds exactly once, using the resolved tempo, right before rendering.

**Why is `/` just division, with no separate "fraction" syntax?** A
duration written as `1/4` should be indistinguishable, to the compiler,
from any other arithmetic expression that happens to evaluate to
`0.25` — e.g. `(1+1)/8`. Giving fractions their own grammar rule would
mean either restricting them to literal-over-literal (rejecting
`base/8` for a `let`-bound `base`) or quietly duplicating the general
expression grammar. Reusing one arithmetic grammar for every numeric
context — tempo, durations, velocities, effect arguments, `let`
values — is both simpler to implement and more expressive.

**Why velocity as a general multiplier rather than fixed dynamic
levels (`pp`/`mf`/`ff`, etc.)?** A continuous `0..1`(+) multiplier
composes trivially with the rest of the arithmetic grammar (`@ base *
0.8`) and lets the one dead-code-elimination pass the compiler has
(velocity-0 elision) fall out for free, rather than needing a special
"silent" dynamic marking.

**Why does `slide` require a preceding pitched event instead of taking
an explicit start pitch?** Because a slide is, by definition, a
continuation of whatever the instrument was just doing — writing
`slide E4 : 1/2` right after `note C4 : 1/2` reads the way the music
actually sounds (a glide *from* the last note), and forcing the start
pitch to also be spelled out would just be redundant with the note
that's already there.

**Why is `noise` a deterministic hash of the sample index rather than a
seeded PRNG?** Determinism is the whole point: the same `.tune` program
must render identically every time, and — more specifically for this
project — the noise waveform must be *bit-for-bit reproducible across
three independently written backends* so it stays part of the
numeric-diff testing strategy in §5 below. A `triple32`-style avalanche
hash of the absolute sample index gives noise-like output with zero
hidden state to keep in sync between backends.

## 5. Why Three Backends

A synthesis backend can have a bug that still compiles, still runs, and
still produces *some* audio — just subtly wrong audio (an off-by-one
sample, a phase discontinuity, a filter recurrence applied in the wrong
order). That class of bug is easy to miss by ear and easy to miss with
only unit tests that check "did it produce a file of the right length."

Keeping `reference.py` intentionally simple and treating it as ground
truth turns backend correctness into a numeric question: render the
same `SemanticResult` on two backends and diff the sample arrays. This
is why `codegen.py`'s C++ output goes to great lengths to match
`reference.py`'s exact rounding behavior (Python's round-half-to-even
vs. C++'s round-half-away-from-zero) and its exact noise-hash constants
— any divergence there would otherwise show up as small, hard-to-track
sample differences instead of a clean pass/fail.

## 6. Non-Goals

Explicitly not attempted: real-time/live performance, MIDI *input*,
stereo/spatial audio, physical modeling of real instrument timbres, any
form of user interaction at render time, and (for now) a plugin/
extension mechanism for adding waveforms or effects without touching
all three backends. See
[05_LANGUAGE_EVOLUTION.md](05_LANGUAGE_EVOLUTION.md) for which of these
are plausible future directions versus permanently out of scope.
