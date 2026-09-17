#!/usr/bin/env python3
"""
Tune DSL — chord-sheet compiler.

Converts one or more chord-sheet files (song_name.guitar, song_name.
keyboard, song_name.veena, etc. -- the extension names the instrument,
see src/chordsheet.py's INSTRUMENT_DEFAULTS for the supported set) into
Tune DSL source, then compiles and plays/exports it through the same
backends tune.py uses.

Single instrument:
    python3 chordsheet_cli.py kangal_irandal.guitar
        -> writes kangal_irandal.wav

Multiple instruments for the same song, layered together:
    python3 chordsheet_cli.py kangal_irandal.guitar kangal_irandal.keyboard kangal_irandal.bass
        -> writes kangal_irandal.wav with all three layered

Just see the generated Tune source without compiling:
    python3 chordsheet_cli.py kangal_irandal.guitar --to-tune
        -> prints the converted .tune source to stdout

IMPORTANT, read this: a chord-sheet file only carries chord names,
tempo, and the rhythm/durations YOU specify -- see the module docstring
in src/chordsheet.py for why this can't magically reproduce a specific
recording's exact arrangement, only the chords and timing you encode.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from chordsheet import chordsheet_to_tune, parse_chordsheet, ChordSheetError, INSTRUMENT_DEFAULTS
from parser import parse, ParseError
from semantic import analyze, SemanticError
from lexer import LexError
import reference as ref

from tune import compile_cpp_backend, compile_mlir_backend


def instrument_from_filename(path: str) -> str:
    ext = os.path.splitext(path)[1].lstrip(".")
    return ext


def main():
    ap = argparse.ArgumentParser(
        description="Convert chord-sheet file(s) (song.guitar, song.keyboard, ...) to audio.",
        epilog=f"Supported instruments (file extensions): {', '.join(sorted(INSTRUMENT_DEFAULTS))}",
    )
    ap.add_argument("sources", nargs="+", help="one or more song_name.<instrument> chord-sheet files")
    ap.add_argument("-o", "--output", help="output .wav path (default: derived from the first input file)")
    ap.add_argument("--backend", choices=["python", "cpp", "mlir"], default="python")
    ap.add_argument("--export-midi", metavar="PATH", help="also export a Standard MIDI File")
    ap.add_argument("--to-tune", action="store_true",
                     help="don't compile -- just print the converted Tune source to stdout")
    args = ap.parse_args()

    for path in args.sources:
        if not os.path.isfile(path):
            print(f"error: no such file: {path}", file=sys.stderr)
            sys.exit(1)

    # decide instrument for each file from its extension, and give each a
    # unique Tune instrument/pattern name so multiple files can be merged
    # without name collisions (e.g. two files both using "guitar" waveform
    # defaults but distinguished by their own instrument name)
    blocks = []
    combined_tempo = None
    for i, path in enumerate(args.sources):
        instrument_key = instrument_from_filename(path)
        if instrument_key not in INSTRUMENT_DEFAULTS:
            print(
                f"error: {path!r} has extension '.{instrument_key}', which isn't a "
                f"recognized instrument (supported: {', '.join(sorted(INSTRUMENT_DEFAULTS))})",
                file=sys.stderr,
            )
            sys.exit(1)

        with open(path) as f:
            text = f.read()

        try:
            file_tempo, _entries = parse_chordsheet(text)
        except ChordSheetError as e:
            print(f"error in {path}: {e}", file=sys.stderr)
            sys.exit(1)
        if file_tempo is not None and combined_tempo is None:
            combined_tempo = file_tempo
        elif file_tempo is not None and file_tempo != combined_tempo:
            print(
                f"warning: {path} specifies tempo {file_tempo}, but the combined "
                f"tempo is already {combined_tempo} (from an earlier file) -- "
                f"using {combined_tempo} for all files",
                file=sys.stderr,
            )

        instrument_name = f"{instrument_key}_{i}" if len(args.sources) > 1 else instrument_key
        pattern_name = f"{instrument_key}_{i}_pattern" if len(args.sources) > 1 else f"{instrument_key}_pattern"

        try:
            block = chordsheet_to_tune(
                text, instrument_key,
                instrument_name=instrument_name, pattern_name=pattern_name,
                include_tempo=False,
            )
        except ChordSheetError as e:
            print(f"error in {path}: {e}", file=sys.stderr)
            sys.exit(1)
        blocks.append(block)

    tempo_line = f"tempo {combined_tempo:g}\n" if combined_tempo is not None else ""
    tune_src = tempo_line + "\n".join(blocks)

    if args.to_tune:
        print(tune_src)
        return

    try:
        program = parse(tune_src)
        result = analyze(program)
    except (LexError, ParseError, SemanticError) as e:
        print(f"internal error converting chord sheet(s) to Tune source: {e}", file=sys.stderr)
        print("---- generated source ----", file=sys.stderr)
        print(tune_src, file=sys.stderr)
        sys.exit(1)

    base = os.path.splitext(args.sources[0])[0]
    out_path = args.output or base + ".wav"

    if args.backend == "cpp":
        compile_cpp_backend(result, out_path)
    elif args.backend == "mlir":
        compile_mlir_backend(result, out_path)
    else:
        samples = ref.render_program(result)
        ref.write_wav(out_path, samples)
        duration = len(samples) / ref.SAMPLE_RATE
        print(f"wrote {out_path} ({duration:.2f}s, tempo {result.tempo_bpm:.0f} bpm, "
              f"{len(args.sources)} instrument(s))")

    if args.export_midi:
        from midi_export import export_midi
        export_midi(result, args.export_midi)
        print(f"wrote {args.export_midi} (MIDI)")


if __name__ == "__main__":
    main()