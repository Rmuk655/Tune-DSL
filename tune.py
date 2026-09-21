#!/usr/bin/env python3
"""
Tune DSL — command-line compiler/player.

Usage:
    python3 tune.py mysong.tune                # writes mysong.wav
    python3 tune.py mysong.tune -o out.wav      # custom output path
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from lexer import LexError
from parser import parse, ParseError
from semantic import analyze, SemanticError
import reference as ref


def compile_cpp_backend(result, out_path):
    """Generate, compile, and run the C++ backend. Requires g++ on PATH."""
    import subprocess
    import shutil
    import tempfile
    from codegen import generate_cpp, CppBackendError

    if shutil.which("g++") is None:
        print("error: g++ not found on PATH -- required for --backend cpp", file=sys.stderr)
        sys.exit(1)

    try:
        cpp_src = generate_cpp(result)
    except CppBackendError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    with tempfile.TemporaryDirectory() as tmpdir:
        cpp_path = os.path.join(tmpdir, "song.cpp")
        exe_path = os.path.join(tmpdir, "song")
        with open(cpp_path, "w") as f:
            f.write(cpp_src)

        compile_result = subprocess.run(
            ["g++", "-O3", "-march=native", "-ffast-math", "-flto", "-funroll-loops", "-o", exe_path, cpp_path],
            capture_output=True, text=True,
        )
        if compile_result.returncode != 0:
            print("error: g++ failed to compile generated C++:", file=sys.stderr)
            print(compile_result.stderr, file=sys.stderr)
            sys.exit(1)

        run_result = subprocess.run([exe_path, out_path], capture_output=True, text=True)
        if run_result.returncode != 0:
            print("error: compiled binary failed to run:", file=sys.stderr)
            print(run_result.stderr, file=sys.stderr)
            sys.exit(1)
        print(run_result.stdout.strip())


def compile_mlir_backend(result, out_path):
    """Generate, lower (mlir-opt -> mlir-translate -> llc), compile, and
    run the MLIR backend. Requires mlir-opt-19, mlir-translate-19, llc-19,
    and gcc on PATH. Full feature parity with the C++ backend -- all 6
    waveforms, velocity, and all 5 effects. See src/codegen_mlir.py."""
    from codegen_mlir import compile_and_run_mlir, MlirBackendError
    try:
        output = compile_and_run_mlir(result, out_path)
        print(output)
    except MlirBackendError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="Compile a .tune file to a .wav file.")
    ap.add_argument("source", help="path to a .tune source file")
    ap.add_argument("-o", "--output", help="output .wav path (default: same name, .wav)")
    ap.add_argument("--backend", choices=["python", "cpp", "mlir"], default="python",
                     help="synthesis backend: 'python' (default, numpy, full language "
                          "support including slide/envelope), 'cpp' (compiles generated "
                          "C++ with g++), or 'mlir' (lowers via mlir-opt/mlir-translate/"
                          "llc). cpp and mlir support everything EXCEPT `slide` and "
                          "per-instrument `envelope` overrides -- use --backend python "
                          "for those, or see src/codegen.py / src/codegen_mlir.py.")
    ap.add_argument("--export-midi", metavar="PATH",
                     help="also write a Standard MIDI File (.mid) to PATH -- notes/timing/"
                          "velocity only, `effect` statements have no MIDI equivalent and "
                          "are not included (see src/midi_export.py)")
    ap.add_argument("--compare-to", metavar="EXPECTED_WAV",
                     help="after rendering, compare the output against a reference WAV "
                          "file (EXPECTED_WAV = the 'expected' audio, the freshly rendered "
                          "file = 'actual') and print a numeric similarity report -- see "
                          "src/audio_compare.py for exactly what these numbers mean "
                          "(a correlation-based heuristic, not a perceptual judgment)")
    args = ap.parse_args()

    if not os.path.isfile(args.source):
        print(f"error: no such file: {args.source}", file=sys.stderr)
        sys.exit(1)

    with open(args.source, "r") as f:
        src = f.read()

    out_path = args.output or os.path.splitext(args.source)[0] + ".wav"

    try:
        program = parse(src)
        result = analyze(program)
    except LexError as e:
        print(f"lex error: {e}", file=sys.stderr)
        sys.exit(1)
    except ParseError as e:
        print(f"parse error: {e}", file=sys.stderr)
        sys.exit(1)
    except SemanticError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    if not result.plays:
        print("warning: no `play` statements found — output will be silent", file=sys.stderr)

    if args.backend == "cpp":
        compile_cpp_backend(result, out_path)
    elif args.backend == "mlir":
        compile_mlir_backend(result, out_path)
    else:
        samples = ref.render_program(result)
        ref.write_wav(out_path, samples)
        duration = len(samples) / ref.SAMPLE_RATE
        print(f"wrote {out_path} ({duration:.2f}s, tempo {result.tempo_bpm:.0f} bpm)")

    if args.export_midi:
        from midi_export import export_midi
        export_midi(result, args.export_midi)
        print(f"wrote {args.export_midi} (MIDI)")

    if args.compare_to:
        from audio_compare import compare_files, render_report, AudioCompareError
        if not os.path.isfile(args.compare_to):
            print(f"error: --compare-to file not found: {args.compare_to}", file=sys.stderr)
            sys.exit(1)
        try:
            metrics = compare_files(args.compare_to, out_path)
        except AudioCompareError as e:
            print(f"error comparing audio: {e}", file=sys.stderr)
            sys.exit(1)
        print()
        print(render_report(metrics, args.compare_to, out_path))


if __name__ == "__main__":
    main()