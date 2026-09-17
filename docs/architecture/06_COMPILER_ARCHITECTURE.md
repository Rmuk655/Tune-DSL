# 6. Compiler Architecture

## 6.1 Pipeline Overview

```text
.tune source
   │
   ▼
lexer.py        tokenize()          source text -> Token stream
   │
   ▼
parser.py       parse()             tokens -> AST (ast_nodes.py)
   │
   ▼
semantic.py     analyze()           AST -> SemanticResult
   │                                 (constant folding, pattern
   │                                  flattening, DCE, validation)
   │
   ├──────────────┬──────────────────┬───────────────────────┐
   ▼              ▼                  ▼                       ▼
reference.py   codegen.py       codegen_mlir.py         midi_export.py
(Python/NumPy) (generate+g++)   (generate+mlir toolchain) (SMF writer)
   │              │                  │                       │
   ▼              ▼                  ▼                       ▼
 .wav           .wav               .wav                    .mid
```

A second, independent front end feeds the same pipeline from a
different source format:

```text
.guitar / .bass / ... (chord sheet)
   │
   ▼
chord_theory.py   resolve_chord()    chord symbol -> pitch names
   │
   ▼
chordsheet.py     chordsheet_to_tune()   chord-sheet text -> Tune DSL source
   │
   ▼
   (feeds into the same lexer.py -> parser.py -> semantic.py -> backend pipeline above)
```

## 6.2 Module Map

| Module | Responsibility |
|---|---|
| `src/pitch.py` | Pitch name (`"C4"`, `"Bb3"`) ↔ frequency (Hz). No other module does this conversion independently. |
| `src/lexer.py` | Source text → `Token` stream. Pitch-vs-identifier disambiguation happens here (§6.3). |
| `src/ast_nodes.py` | Plain dataclasses for every AST node — no behavior, shared by parser/semantic/codegen. |
| `src/parser.py` | Recursive-descent parser, tokens → AST. Standard 3-level expression precedence climb. |
| `src/semantic.py` | AST → `SemanticResult`. The only module that evaluates expressions, resolves `let`, or flattens `pattern`/`repeat` structure into absolute-time events. |
| `src/reference.py` | Backend 1 (ground truth): NumPy synthesizer + hand-rolled WAV writer. |
| `src/codegen.py` | Backend 2: generates a self-contained C++ program, compiles it with `g++`, runs it. |
| `src/codegen_mlir.py` | Backend 3: generates a small generic MLIR function library, lowers it through `mlir-opt-19`/`mlir-translate-19`/`llc-19`, links with `gcc`, runs it. |
| `src/midi_export.py` | `SemanticResult` → Standard MIDI File (hand-rolled byte-level writer). |
| `src/chord_theory.py` | Chord symbol (`"Am7"`, `"C/E"`) → pitch names. |
| `src/chordsheet.py` | Chord-sheet text → Tune DSL source text (feeds back into `lexer.py`). |
| `tune.py` | CLI: wires lexer → parser → semantic → a chosen backend, plus optional MIDI export. |
| `chordsheet_cli.py` | CLI: one or more chord-sheet files → combined Tune source → same backend pipeline as `tune.py`. |
| `gui/app.py` | Flask routes calling the exact same modules above — no compiler logic lives in the GUI layer. |

The front end (`pitch.py` → `lexer.py` → `parser.py` → `semantic.py`)
is entirely backend-agnostic: every backend consumes only
`SemanticResult` (see
[INTERFACES.md](INTERFACES.md#semanticresult)), never the AST directly.

## 6.3 Lexer Notes

The pitch-vs-identifier disambiguation is the lexer's one genuinely
subtle piece: on seeing a letter, it must decide whether it's starting
a pitch literal (`C4`) or a plain identifier (`chord`, `lead`) *before*
committing to either token type. The rule: a letter `A`-`G`, optionally
followed by `s`/`b`, followed by exactly one digit, with no further
alphanumeric/`_` character immediately after, lexes as `PITCH`;
anything else scanned as a letter run lexes as an identifier (checked
against the keyword table) or `IDENT`. This check must run *before* the
general identifier scan, or `C4` would lex as identifier `C` followed
by int `4`.

## 6.4 Semantic Analysis — Two Passes

1. **Collect declarations** (one pass over top-level statements, in
   source order): resolves `tempo`, validates and stores each
   `instrument`'s waveform + envelope, evaluates and stores each `let`,
   stores each `pattern`'s raw AST (not yet flattened), validates each
   `effect`'s name/arity and evaluates its arguments, and collects
   `play` statements for later validation.
2. **Flatten and validate `play`s**: for each `play`, validate both
   names exist, then (if not already cached for that pattern name)
   recursively flatten the pattern's body into a list of `NoteEvent`s
   with absolute `start_beat`s — walking `note`/`chord`/`rest`/`slide`/
   `strum`/`repeat` and threading a running beat cursor and "last
   pitched frequency" (needed by `slide`) through nested `repeat`
   unrolling.

Velocity-exactly-0 events are dropped during flattening (counted in
`SemanticResult.dce_eliminated`) but still advance the beat cursor and
update "last pitched frequency" — the one thing eliminated is the
synthesis work, never the timing.

## 6.5 The Three Backends

### 6.5.1 Python/NumPy (`reference.py`) — ground truth

Per-event: build a phase array, look up the waveform (a phase function
for 5 of the 6; `noise` instead hashes the absolute sample index and
ignores phase/frequency entirely), apply the attack/release envelope,
scale by velocity, add into the mix buffer. `slide` events integrate a
linearly-ramping frequency over time for phase, rather than
`freq(t)*t`, to avoid a phase discontinuity. Effects run in declaration
order; two of the five (`lowpass`, `highpass`) are true recurrences and
run in a plain Python loop, the other three vectorize directly. Output
is peak-normalized to 0.95 and written with a hand-rolled 16-bit PCM
mono WAV writer.

### 6.5.2 C++ (`codegen.py`)

Emits one self-contained `.cpp` file, compiled with `g++ -O3
-march=native -ffast-math -flto -funroll-loops`. Key design choices
(each with its own rationale in
[DECISIONS.md](DECISIONS.md#arch-001-round-durations-in-python-not-c)):
all sample-count rounding happens in Python and is baked into the
generated source as literal integers; waveform dispatch is a C++
template specialization (compile-time, not a runtime `switch` in the
hot loop) so GCC can auto-vectorize; phase wrapping uses `raw -
std::floor(raw)` rather than `std::fmod` for the same vectorization
reason. Rejects `slide`/custom-`envelope` sources immediately, before
generating any code.

### 6.5.3 MLIR (`codegen_mlir.py`)

Builds one small, generic, reusable function library — `@synth_event`
(covering all 6 waveforms via a genuine runtime `scf.index_switch`) and
one `@apply_*` function per effect — called once per event/effect,
rather than unrolling specialized per-event code. Uses only standard
MLIR dialects (`func`, `arith`, `scf`, `memref`, `math`, `index`) — no
custom dialect. Pipeline: `mlir-opt-19` (lowers to the `llvm` dialect)
→ `mlir-translate-19` (to LLVM IR text) → `llc-19` (to a native object
file) → `gcc` (links with a small C driver + WAV writer). The
`mlir_test/` directory holds standalone prototypes that were compiled
through this exact pipeline and numerically diffed against
`reference.py`, per waveform and per effect, before being folded into
the real generator. Same `slide`/`envelope` restriction as the C++
backend.

## 6.6 MIDI Export

`midi_export.py` walks the same `SemanticResult` used by the WAV
backends — it does not re-parse or re-analyze anything. One MIDI track
per `play` statement; PPQ 480; the tempo meta-event is written once, on
the first track; frequencies are converted back to the nearest MIDI
note number (the exact inverse of `pitch.py`'s conversion); velocity is
mapped to MIDI's `[1,127]` range with a floor of 1 (a note-on at
velocity 0 is treated by some players as a note-off, so quiet-but-
audible notes are never allowed to round down to it). `effect`
statements have no MIDI representation and are not exported — a
property of the MIDI format, not a limitation of this writer.

## 6.7 The GUI Is Not a Separate Implementation

`gui/app.py` imports `lexer`, `parser`, `semantic`, and the backend
modules directly — every `/api/compile` request runs through the exact
same `parse → analyze → render` path as `tune.py`. This is a deliberate
architectural constraint: the web UI is a thin transport layer, not a
second compiler that could drift from the CLI's behavior.

## 6.8 Data Flow Summary

The one representation every backend, `midi_export.py`, and the GUI
all consume is `SemanticResult` (and, within it, the list of
`NoteEvent`s per played pattern) — see
[INTERFACES.md](INTERFACES.md) for its exact shape. Nothing downstream
of semantic analysis ever looks at the AST again.
