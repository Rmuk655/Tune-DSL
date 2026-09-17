# Dependencies

## 1. Python packages

| Package | Why | Required for |
|---|---|---|
| `numpy` | The Python/NumPy synthesis backend (`reference.py`) — the only backend used by default, and the only one every other backend is checked against. | Core compiler (`tune.py`, `chordsheet_cli.py`) with `--backend python` (default) |
| `flask` | Web server for `gui/app.py`. | Web GUI only |
| `mido` | An independent MIDI-file *reader*, used exclusively by the test suite to validate `midi_export.py`'s hand-rolled writer against a library that didn't write the file. Never used to write MIDI in the project itself — keeping the writer and its verification independent is the point. | `pytest tests/test_midi_export.py` only |
| `pytest` | Test runner. | Running the test suite |

No `requirements.txt` ships with the project; `pip install numpy flask
mido pytest` covers everything above.

## 2. External toolchains (not pip packages)

| Tool | Why | Required for |
|---|---|---|
| `g++` (any recent GCC, C++17+) | `codegen.py` generates a `.cpp` file and shells out to `g++ -O3 -march=native -ffast-math -flto -funroll-loops` to compile it, then runs the result. | `--backend cpp` |
| `mlir-opt-19` | Lowers the generated MLIR (standard dialects only — `func`/`arith`/`scf`/`memref`/`math`/`index`) to the `llvm` dialect. | `--backend mlir` |
| `mlir-translate-19` | Translates `llvm`-dialect MLIR to LLVM IR text. | `--backend mlir` |
| `llc-19` | Compiles LLVM IR to a native object file. | `--backend mlir` |
| `gcc` | Links the object file above with a small C driver + WAV writer into a runnable binary. | `--backend mlir` |

The MLIR toolchain is the one place where the exact major version
matters: `codegen_mlir.py`'s generated IR text targets MLIR 19's
syntax specifically, so a different major version's tools may reject
it or behave differently. `g++` has no such version pin — any
reasonably recent GCC works, since the generated C++ only uses
ordinary C++17 features plus standard optimization flags.

## 3. What has no dependency at all

- **The WAV writer** (`reference.py`'s `write_wav`, and each backend's
  own port of it) is hand-rolled at the byte level — no `wave` module,
  no audio library.
- **The MIDI writer** (`midi_export.py`) is likewise hand-rolled at the
  byte level — `mido` is used only to *read back* and check its output
  in tests, never to produce it.
- **Chord theory and chord-sheet parsing** (`chord_theory.py`,
  `chordsheet.py`) are pure Python string/regex processing — no
  dependency beyond the standard library.

## 4. Checking what's available on a given machine

There's no bundled `check-deps.sh`-style script; the simplest checks:

```bash
python3 -c "import numpy"                       # core compiler
which g++                                         # C++ backend
which mlir-opt-19 mlir-translate-19 llc-19 gcc     # MLIR backend
python3 -c "import flask"                        # web GUI
python3 -c "import pytest, mido"                 # test suite
```

`tune.py` and the test suite both detect a missing external tool
themselves at the point it's needed and report it by name (or, for
tests, skip with a clear reason — see
[../testing/TEST_MATRIX.md](../testing/TEST_MATRIX.md#skip-conditions))
rather than failing with an opaque error, so none of the checks above
are strictly necessary before trying a command — they're just faster
than waiting for a run to fail.
