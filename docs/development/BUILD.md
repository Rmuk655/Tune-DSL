# Building and Running Tune DSL

## Canonical platform

Pure Python 3 (developed/tested at 3.12) plus NumPy for the core
compiler and Python backend — this runs on Linux, macOS, or Windows
with no OS-specific steps. The optional C++ and MLIR backends need
their respective external toolchains (§3 below) and are most easily
set up on Linux (the project's own bundled `venv/` targets Linux
x86_64/Python 3.12).

## 1. Core setup (always required)

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install numpy
```

This alone is enough for `--backend python` (the default), the
chord-sheet CLI, and MIDI export.

## 2. Optional: web GUI

```bash
pip install flask
python3 gui/app.py
# open http://127.0.0.1:5000
```

## 3. Optional: C++ backend

Needs `g++` on `PATH` (any recent GCC with C++17 support). No pip
package required — `codegen.py` shells out to `g++` directly.

```bash
sudo apt install g++          # Debian/Ubuntu
# or: xcode-select --install  # macOS
```

```bash
python3 tune.py examples/melody.tune --backend cpp
```

If `g++` isn't found on `PATH`, `tune.py` reports this clearly rather
than failing with a raw `subprocess` error.

## 4. Optional: MLIR backend

Needs the LLVM/MLIR 19 command-line tools, specifically
`mlir-opt-19`, `mlir-translate-19`, and `llc-19`, plus `gcc` for the
final link step:

```bash
sudo apt install llvm-19 mlir-19-tools    # exact package names vary by distro/release
```

```bash
python3 tune.py examples/melody.tune --backend mlir
```

Any missing tool is detected and reported by name, rather than the
pipeline failing partway through with an opaque `subprocess` error.
This is the one dependency where the exact major version matters —
`codegen_mlir.py`'s generated IR is written against MLIR 19's syntax.

## 5. Optional: test suite

```bash
pip install pytest mido
pytest tests/
```

`mido` is used only as an independent MIDI-file *reader*, to validate
`midi_export.py`'s output against a library other than the one that
wrote it — never to write MIDI in the project itself. Without the C++
and MLIR toolchains installed, the corresponding tests are skipped
(not failed) — see
[../testing/TEST_MATRIX.md](../testing/TEST_MATRIX.md#skip-conditions)
for exactly which tests that affects and why.

## Canonical commands, once set up

```bash
# compile a .tune program to .wav
python3 tune.py song.tune
python3 tune.py song.tune -o out.wav
python3 tune.py song.tune --backend cpp
python3 tune.py song.tune --backend mlir
python3 tune.py song.tune --export-midi song.mid

# compile a chord progression to .wav
python3 chordsheet_cli.py song.guitar
python3 chordsheet_cli.py song.guitar song.bass song.keyboard   # layered
python3 chordsheet_cli.py song.guitar --to-tune                 # inspect generated source only

# run the test suite
pytest tests/

# run the web GUI
python3 gui/app.py
```

## Verifying your setup

A minimal end-to-end check that doesn't depend on any optional
toolchain:

```bash
python3 tune.py examples/melody.tune -o /tmp/check.wav
# wrote /tmp/check.wav (...s, tempo 110 bpm)
```

If you've installed the C++ and/or MLIR toolchains, cross-check them
against the Python backend for the same source — this is the whole
reason the project keeps three independent backends (see
[../architecture/06_COMPILER_ARCHITECTURE.md §6.5](../architecture/06_COMPILER_ARCHITECTURE.md#65-the-three-backends)):

```bash
python3 tune.py examples/melody.tune --backend cpp -o /tmp/check_cpp.wav
python3 tune.py examples/melody.tune --backend mlir -o /tmp/check_mlir.wav
```

All three should sound identical and be numerically close, sample for
sample (the test suite's `*_matches_python_reference` tests assert
this directly rather than relying on listening).
