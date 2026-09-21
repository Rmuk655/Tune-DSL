#!/usr/bin/env python3
"""
Tune DSL — standalone audio-to-source transcription CLI.

Best-effort, MONOPHONIC pitch/onset transcription of an audio file
into a starting-point Tune DSL `pattern` — meant to be tuned by hand
afterward, not a finished/accurate transcription. See
src/audio_transcribe.py's module docstring for exactly what this can
and can't do (no chords/polyphony, pitch/timing/velocity are all
best-effort guesses).

Typical workflow this is built for:
    1. python3 transcribe_audio.py my_hum.wav -o draft.tune
    2. open draft.tune, fix the notes/durations/velocities by ear
    3. python3 tune.py draft.tune --compare-to my_hum.wav
       (see how close your tuned version now renders vs. the original)

Usage:
    python3 transcribe_audio.py input.wav                    # prints to stdout
    python3 transcribe_audio.py input.wav -o draft.tune
    python3 transcribe_audio.py input.wav -o draft.tune --tempo 100
    python3 transcribe_audio.py input.wav --waveform triangle
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from audio_transcribe import transcribe_to_tune, TranscribeError

WAVEFORMS = ["sine", "square", "saw", "triangle", "pulse", "noise"]


def main():
    ap = argparse.ArgumentParser(
        description="Transcribe an audio file into a draft Tune DSL source file. "
                    "Monophonic, best-effort -- meant to be tuned by hand afterward."
    )
    ap.add_argument("source", help="path to a WAV file to transcribe")
    ap.add_argument("-o", "--output", help="write generated Tune source here (default: print to stdout)")
    ap.add_argument("--tempo", type=float, default=None,
                     help="assume this tempo (BPM) instead of estimating one from onset "
                          "spacing -- estimating is a rough guess (see src/audio_transcribe.py); "
                          "supplying the real tempo, if you know it, will make durations snap "
                          "to much more sensible fractions of a beat")
    ap.add_argument("--waveform", choices=WAVEFORMS, default="sine",
                     help="waveform for the generated `instrument` declaration (default: sine)")
    args = ap.parse_args()

    if not os.path.isfile(args.source):
        print(f"error: no such file: {args.source}", file=sys.stderr)
        sys.exit(1)

    try:
        source_text = transcribe_to_tune(args.source, tempo_bpm=args.tempo, waveform=args.waveform)
    except TranscribeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        with open(args.output, "w") as f:
            f.write(source_text)
        print(f"wrote {args.output} -- open it and tune by ear; pitch/timing are best-effort guesses")
    else:
        print(source_text)


if __name__ == "__main__":
    main()