# Tune DSL

A small domain-specific language for writing music as text and
compiling it to real audio. You declare a tempo, one or more
instruments, and named patterns of notes/chords/rests; the compiler
resolves everything at compile time and renders a finished `.wav` file
(or exports a Standard MIDI File). There is no runtime and no live
playback engine — a `.tune` program is a fixed, finite score.

```
source.tune -> lexer -> parser -> AST -> semantic analysis
            -> flattened note events -> synthesis backend -> song.wav
```

## Highlights

- **Three independently implemented synthesis backends**, numerically
  cross-checked against each other: a Python/NumPy reference
  implementation (ground truth), a generated-and-compiled C++ backend,
  and a generated-and-lowered MLIR backend built entirely on standard
  MLIR dialects (no custom "Tune dialect").
- 6 waveforms, 5 global audio effects, velocity, chord/strum/slide
  syntax, per-instrument envelope overrides.
- A companion **chord-sheet** mini-format (`.guitar`, `.bass`,
  `.keyboard`, ...) for turning a chord progression worked out by ear
  into a real, compiled, multi-instrument arrangement.
- **MIDI export** for taking a program's notes into a DAW.
- A **Flask web GUI** that runs the exact same compiler pipeline as the
  command line.
- A 242-test `pytest` suite, including sample-level numeric diffs
  between backends.

This is a personal/hackathon project (not a graded team project), built
solo. See [docs/ProjectMgmt/01_INTRODUCTION.md](docs/ProjectMgmt/01_INTRODUCTION.md)
for the fuller motivation.

## Quickstart

```bash
python3 -m venv venv && source venv/bin/activate
pip install numpy flask mido pytest

python3 tune.py examples/melody.tune
# wrote examples/melody.wav (1.64s, tempo 110 bpm)
```

```tune
tempo 110
instrument lead = sine
pattern melody {
  note C4 : 1/4
  note D4 : 1/4
  note E4 : 1/2
}
play lead melody
```

See [docs/language/02_LANGUAGE_TUTORIAL.md](docs/language/02_LANGUAGE_TUTORIAL.md)
to start writing songs, or
[docs/development/BUILD.md](docs/development/BUILD.md) for the full
setup (including the optional C++/MLIR toolchains).

## Documentation map

| Doc | What's in it |
|---|---|
| [docs/ProjectMgmt/01_INTRODUCTION.md](docs/ProjectMgmt/01_INTRODUCTION.md) | Motivation, objectives, scope, known limitations |
| [docs/ProjectMgmt/09_CONCLUSIONS_LESSONS_LEARNED.md](docs/ProjectMgmt/09_CONCLUSIONS_LESSONS_LEARNED.md) | What building three independent audio backends actually taught |
| [docs/ProjectMgmt/12_PROJECT_FAQ.md](docs/ProjectMgmt/12_PROJECT_FAQ.md) | Design defense / demo script / anticipated questions |
| [docs/language/00_WHITEPAPER.md](docs/language/00_WHITEPAPER.md) | Why a music DSL, why these design choices |
| [docs/language/02_LANGUAGE_TUTORIAL.md](docs/language/02_LANGUAGE_TUTORIAL.md) | Learn Tune by writing songs, example by example |
| [docs/language/03_LANGUAGE_REFERENCE_MANUAL.md](docs/language/03_LANGUAGE_REFERENCE_MANUAL.md) | The normative grammar and semantics |
| [docs/language/05_LANGUAGE_EVOLUTION.md](docs/language/05_LANGUAGE_EVOLUTION.md) | v1 scope freeze, what's explicitly out, likely v2 candidates |
| [docs/architecture/06_COMPILER_ARCHITECTURE.md](docs/architecture/06_COMPILER_ARCHITECTURE.md) | Pipeline stages, module map, the three backends |
| [docs/architecture/DECISIONS.md](docs/architecture/DECISIONS.md) | Architecture Decision Records — the *why* behind non-obvious code |
| [docs/architecture/INTERFACES.md](docs/architecture/INTERFACES.md) | The data shapes that cross module boundaries (`Token`, AST nodes, `SemanticResult`, `NoteEvent`) |
| [docs/development/BUILD.md](docs/development/BUILD.md) | Install, build, run, per-backend requirements |
| [docs/development/DEPENDENCIES.md](docs/development/DEPENDENCIES.md) | Every dependency and why it's needed |
| [docs/testing/TEST_MATRIX.md](docs/testing/TEST_MATRIX.md) | What the 242-test suite actually covers, file by file |
| [docs/testing/KNOWN_BUGS.md](docs/testing/KNOWN_BUGS.md) | Known, by-design limitations (there are no open defects at time of writing) |

## Project layout

```
TuneDSL/
├── tune.py                  # CLI: compile a .tune file to .wav / .mid
├── chordsheet_cli.py         # CLI: chord-sheet file(s) -> audio
├── play_my_song.py            # standalone example script
├── src/
│   ├── lexer.py  ast_nodes.py  parser.py  pitch.py  semantic.py
│   ├── reference.py                # backend 1: Python/NumPy (ground truth)
│   ├── codegen.py                   # backend 2: generates + compiles C++
│   ├── codegen_mlir.py               # backend 3: generates + lowers MLIR
│   ├── midi_export.py
│   └── chord_theory.py  chordsheet.py
├── gui/            # Flask web GUI over the same src/ pipeline
├── examples/       # sample .tune programs and chord sheets
├── mlir_test/      # standalone MLIR prototypes, verified before embedding
└── tests/          # pytest suite (242 tests, one file per module)
```
