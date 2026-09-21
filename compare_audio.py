#!/usr/bin/env python3
"""
Tune DSL — standalone audio comparison CLI.

Compares any two WAV files directly (doesn't need to know anything
about Tune source at all) — useful for comparing a Tune-rendered file
against a reference recording after the fact, or for comparing two
renders of the same source against each other (e.g. --backend python
vs --backend cpp output, to sanity-check backend parity by ear AND by
number — see docs/architecture/06_COMPILER_ARCHITECTURE.md §6.5).

If tune.py or chordsheet_cli.py just rendered your output, it's
usually more convenient to pass --compare-to directly to those instead
(see their --help) — this standalone script is for comparing two
existing files without recompiling anything.

Usage:
    python3 compare_audio.py expected.wav actual.wav
    python3 compare_audio.py expected.wav actual.wav --plot diff.png
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from audio_compare import compare_files, render_report, plot_comparison, AudioCompareError
from audio_io import load_wav_mono, resample_linear


def main():
    ap = argparse.ArgumentParser(
        description="Compare two WAV files and print a numeric similarity report. "
                    "See src/audio_compare.py's module docstring for exactly what the "
                    "reported numbers mean (a correlation-based heuristic, not a "
                    "perceptual/musical-accuracy judgment)."
    )
    ap.add_argument("expected", help="path to the reference/expected WAV file")
    ap.add_argument("actual", help="path to the rendered/actual WAV file")
    ap.add_argument("--plot", metavar="PATH",
                     help="also write a waveform-overlay + spectral-difference PNG to PATH "
                          "(requires matplotlib; skipped with a note if it isn't installed)")
    args = ap.parse_args()

    for path in (args.expected, args.actual):
        if not os.path.isfile(path):
            print(f"error: no such file: {path}", file=sys.stderr)
            sys.exit(1)

    try:
        metrics = compare_files(args.expected, args.actual)
    except AudioCompareError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    print(render_report(metrics, args.expected, args.actual))

    if args.plot:
        expected, sr_e = load_wav_mono(args.expected)
        actual, sr_a = load_wav_mono(args.actual)
        if sr_e != sr_a:
            target = max(sr_e, sr_a)
            expected = resample_linear(expected, sr_e, target)
            actual = resample_linear(actual, sr_a, target)
            sample_rate = target
        else:
            sample_rate = sr_e
        ok = plot_comparison(expected, actual, sample_rate, args.plot)
        if ok:
            print(f"\nwrote {args.plot}")
        else:
            print("\n(skipped --plot: matplotlib is not installed)", file=sys.stderr)


if __name__ == "__main__":
    main()