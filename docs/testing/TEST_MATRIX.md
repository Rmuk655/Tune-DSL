# Test Matrix

242 tests across 13 files, one file per module. Verified by actually
running the suite:

```text
232 passed, 19 skipped in ~13s
```

(skipped tests are all MLIR-toolchain-gated — see "Skip conditions"
below; the environment used for this doc had `g++` available but not
`mlir-opt-19`/`mlir-translate-19`/`llc-19`.)

## Coverage by file

| Test file | Tests | Covers | Notable coverage |
|---|---:|---|---|
| `test_pitch.py` | 12 | `src/pitch.py` | A4=440 exactly; octave doubling; sharp/flat enharmonic equivalence; the B3→C4 octave boundary; invalid pitch class raises |
| `test_lexer.py` | 16 | `src/lexer.py` | Pitch-vs-identifier disambiguation; sharp/flat pitch tokens; float literals; comments ignored; line/col tracking; unexpected-character error |
| `test_parser.py` | 29 | `src/parser.py` | Every statement type; operator precedence (`*`/`/` over `+`/`-`); unary minus; nested `repeat`; blank lines and comments ignored between statements; missing-newline error |
| `test_semantic.py` | 37 | `src/semantic.py` | Tempo default/override; instrument/waveform validation; undeclared-instrument/pattern errors on `play`; note timing accumulation; chord events sharing a start beat; `repeat` unrolling (incl. nested); `let` resolution; undefined-`let` and division-by-zero errors |
| `test_reference.py` | 29 | `src/reference.py` | Render length matches duration; rest silence regions; output never clips; sine frequency verified via FFT; square-wave bimodality; click-avoiding envelope; all waveform shapes; unknown-waveform error; WAV header correctness and out-of-range clipping; multi-`play` mixing; pulse's 25% duty cycle; noise's determinism and boundedness |
| `test_codegen.py` | 24 | `src/codegen.py` | Generated C++ is well-formed and compiles without warnings; rests marked as negative frequency; Python-style rounding (not naive multiply) for sample counts; **numeric match against `reference.py`** for a single note, an arpeggio, a chord, a full multi-instrument song, and each waveform individually (square, pulse, noise's bit-exact hash); velocity handling; vectorization status of the hot loop |
| `test_codegen_mlir.py` | 13 | `src/codegen_mlir.py` | Generated MLIR is a genuine shared function library (no duplicated per-event waveform math); all 6 waveforms and all 5 effects covered; rests produce no synth call; output is valid MLIR and compiles through the real toolchain; **numeric match against `reference.py`** per waveform, per effect, and for a full stress-test song; missing-tool error reported cleanly |
| `test_midi_export.py` | 13 | `src/midi_export.py` | Frequency→MIDI-note conversion round-trips every pitch; tempo meta-event matches source; note timing/pitch/velocity mapping; chords produce simultaneous note-ons; rests produce no note events; one track per `play`; DCE-eliminated notes correctly absent from the export; a program with zero `play`s still produces a valid file; `repeat`-unrolled notes all present |
| `test_chord_theory.py` | 19 | `src/chord_theory.py` | Major/minor/dominant-7th/major-7th/minor-7th/sus/dim/aug/power chords; sharp and flat root spellings; slash chords; minor-seventh not confused with bare minor; invalid chord symbol raises |
| `test_chordsheet.py` | 20 | `src/chordsheet.py` | Progression parsing incl. `tempo`/`beats_per_chord` directives, explicit beat overrides, bar repeats, comments/blank lines; conversion produces parseable Tune source; unknown-instrument and bad-chord-symbol errors; every instrument preset produces valid Tune output; `.bass` plays root only, not the full chord |
| `test_chordsheet_cli.py` | 9 | `chordsheet_cli.py` | Single- and multi-instrument compilation; `--to-tune` mode; unrecognized-extension and bad-chord-symbol errors; missing-file error; conflicting-tempo warning (compiles anyway); MIDI export alongside WAV |
| `test_cli.py` | 8 | `tune.py` | End-to-end compile to WAV; missing-file and syntax-error handling; default output filename derivation; both the C++ and MLIR backends end to end (incl. effects and non-default waveforms on MLIR); MIDI export |
| `test_gui.py` | 13 | `gui/app.py` | Index page loads; examples endpoint lists bundled `.tune` files; compile endpoint on all three backends; lex/parse/semantic error reporting as JSON; no-`play` warning; DCE stats surfaced; MIDI export endpoint and its error handling; unknown-backend fallback |

## Cross-backend numeric verification

The single most load-bearing pattern in the suite, given the project's
own design goal (see
[../ProjectMgmt/09_CONCLUSIONS_LESSONS_LEARNED.md §9.1](../ProjectMgmt/09_CONCLUSIONS_LESSONS_LEARNED.md#91-what-went-well)):
`test_codegen.py` and `test_codegen_mlir.py` each render the same
`SemanticResult` on their respective backend and on `reference.py`,
then assert the resulting sample arrays are numerically close — per
individual waveform, per individual effect, and for a full
multi-instrument song. This is what makes "the fast backend sounds
right" a CI assertion instead of a listening exercise.

## Skip conditions

| Condition | Tests affected |
|---|---|
| `g++` not on `PATH` | Would skip C++-backend tests (none were skipped in the verified run above, since `g++` was present) |
| `mlir-opt-19`/`mlir-translate-19`/`llc-19`/`gcc` not all on `PATH` | All MLIR-backend tests in `test_codegen_mlir.py`, plus the MLIR-backend cases in `test_cli.py` and `test_gui.py` — 19 tests total in the verified run |

Both conditions are detected and reported as a clean `pytest` skip with
a stated reason (e.g. `"mlir-opt-19/mlir-translate-19/llc-19/gcc not
all available on this machine"`), not a failure — a machine without
either toolchain still gets a fully-passing run for everything that
toolchain gates.

## What isn't covered by an automated test

- **Perceptual/listening quality** — the suite verifies numerical
  correctness (matches the reference backend, correct shapes/lengths,
  correct header bytes) but has no notion of "sounds good," which is
  out of scope for an automated test by nature.
- **The bundled `venv/`'s portability** to a machine other than the one
  it was built for — see
  [DEPENDENCIES.md](../development/DEPENDENCIES.md) for building a
  fresh one instead.
