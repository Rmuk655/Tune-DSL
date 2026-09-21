"""
Tune DSL -- best-effort audio -> Tune DSL source transcription.

Honest scope, stated up front (same principle as src/chordsheet.py's
own documented scope, and src/audio_compare.py's): this is a naive,
MONOPHONIC pitch/onset transcriber, built from plain autocorrelation
pitch detection and spectral-flux onset detection -- numpy only, no
ML model, no polyphony/chord detection. It is meant to produce a
rough, editable Tune `pattern` to START tuning by hand (per the
feature request this module implements: "get code in the language so
they can tune it"), not a finished, accurate transcription. Expect it
to do reasonably on a single hummed/whistled/plucked melodic line, and
to do poorly on chords, dense polyphonic mixes, or heavily percussive
audio -- it has no way to separate simultaneous pitches, and will
report whichever one pitch dominates each analysis frame.
"""

import numpy as np

from audio_io import load_wav_mono
from pitch import freq_to_pitch_name

MIN_FREQ_HZ = 70.0    # ~D2 -- below this is almost certainly not a sung/played pitch
MAX_FREQ_HZ = 1200.0  # ~D6

# Candidate note durations, in beats, that a detected note's raw duration
# is snapped to -- keeps generated source readable (see
# docs/language/03_LANGUAGE_REFERENCE_MANUAL.md's duration grammar: any of
# these is just an ordinary expression value, nothing special about them).
_DURATION_CANDIDATES = [1 / 8, 1 / 4, 1 / 3, 1 / 2, 3 / 4, 1, 3 / 2, 2, 3, 4]


class TranscribeError(Exception):
    pass


def _detect_pitch_autocorrelation(frame: np.ndarray, sample_rate: int):
    """Autocorrelation-based F0 estimate for one frame, or None if the
    frame doesn't look periodic enough to trust (silence/noise)."""
    frame = frame - frame.mean()
    energy = (frame ** 2).sum()
    if energy < 1e-8:
        return None

    corr = np.correlate(frame, frame, mode="full")
    corr = corr[len(corr) // 2:]
    corr /= corr[0] + 1e-12

    min_lag = int(sample_rate / MAX_FREQ_HZ)
    max_lag = min(int(sample_rate / MIN_FREQ_HZ), len(corr) - 1)
    if max_lag <= min_lag:
        return None

    search = corr[min_lag:max_lag]
    peak_idx = int(np.argmax(search))
    peak_val = search[peak_idx]
    if peak_val < 0.3:  # not periodic enough to call it a pitch
        return None

    lag = min_lag + peak_idx
    return sample_rate / lag


def _spectral_flux_onsets(samples: np.ndarray, sample_rate: int, frame_size: int, hop: int):
    """Simple onset strength curve: positive-only frame-to-frame change
    in FFT magnitude, summed per frame. Used only to segment the audio
    into candidate note boundaries, not for pitch itself."""
    window = np.hanning(frame_size)
    n_frames = max(0, (len(samples) - frame_size) // hop + 1)
    prev_mag = None
    flux = np.zeros(n_frames)
    for i in range(n_frames):
        start = i * hop
        frame = samples[start:start + frame_size] * window
        mag = np.abs(np.fft.rfft(frame))
        if prev_mag is not None:
            diff = mag - prev_mag
            flux[i] = np.sum(diff[diff > 0])
        prev_mag = mag
    return flux


def _segment_notes(samples: np.ndarray, sample_rate: int, frame_size=2048, hop=512):
    """Returns a list of (start_sample, end_sample) candidate note
    segments, split at onset-strength peaks."""
    flux = _spectral_flux_onsets(samples, sample_rate, frame_size, hop)
    if len(flux) == 0:
        return [(0, len(samples))]

    threshold = flux.mean() + 0.75 * flux.std()
    onset_frames = [0]
    for i in range(2, len(flux) - 1):
        if flux[i] > threshold and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1]:
            if i - onset_frames[-1] >= 3:  # avoid two onsets basically on top of each other
                onset_frames.append(i)

    segments = []
    for i, f in enumerate(onset_frames):
        start = f * hop
        end = onset_frames[i + 1] * hop if i + 1 < len(onset_frames) else len(samples)
        if end > start:
            segments.append((start, end))
    return segments


def _snap_duration_beats(raw_beats: float) -> float:
    return min(_DURATION_CANDIDATES, key=lambda d: abs(d - raw_beats))


def _estimate_tempo(segment_lengths_sec, default_bpm=100.0):
    """Rough tempo guess from the median segment length, snapped to the
    nearest 5 BPM -- treated only as a starting point; --tempo always
    overrides it, and the module docstring's honesty note applies here
    specifically: this is a guess to tune by hand, not a beat tracker."""
    lengths = [l for l in segment_lengths_sec if l > 0.05]
    if not lengths:
        return default_bpm
    median_len = float(np.median(lengths))
    # assume the median segment is roughly a quarter note
    bpm = 60.0 / median_len
    bpm = max(40.0, min(240.0, bpm))
    return round(bpm / 5.0) * 5.0


def transcribe_to_events(path: str, tempo_bpm: float = None, waveform: str = "sine"):
    """Core transcription. Returns (tempo_bpm, [(pitch_name_or_None, duration_beats, velocity), ...]).
    pitch_name is None for a rest."""
    samples, sample_rate = load_wav_mono(path)
    if len(samples) < sample_rate // 10:
        raise TranscribeError("audio is too short to transcribe (need at least ~0.1s)")

    segments = _segment_notes(samples, sample_rate)
    peak = np.abs(samples).max() or 1.0

    raw_events = []  # (freq_or_None, duration_sec, velocity)
    for start, end in segments:
        chunk = samples[start:end]
        duration_sec = (end - start) / sample_rate
        rms = np.sqrt((chunk ** 2).mean()) if len(chunk) else 0.0
        velocity = min(1.0, rms / (peak * 0.5))

        if rms < peak * 0.03:  # effectively silent -> rest
            raw_events.append((None, duration_sec, 0.0))
            continue

        # sample pitch at a few points across the segment and take the
        # median -- more robust than one frame, still monophonic-only
        frame_size = min(2048, len(chunk))
        if frame_size < 256:
            raw_events.append((None, duration_sec, 0.0))
            continue
        probe_points = np.linspace(0, max(0, len(chunk) - frame_size), num=3, dtype=int)
        freqs = []
        for p in probe_points:
            f = _detect_pitch_autocorrelation(chunk[p:p + frame_size], sample_rate)
            if f is not None:
                freqs.append(f)
        if not freqs:
            raw_events.append((None, duration_sec, 0.0))
            continue
        raw_events.append((float(np.median(freqs)), duration_sec, velocity))

    if tempo_bpm is None:
        tempo_bpm = _estimate_tempo([dur for _, dur, _ in raw_events])

    events = []
    for freq, duration_sec, velocity in raw_events:
        duration_beats_raw = duration_sec * (tempo_bpm / 60.0)
        duration_beats = _snap_duration_beats(duration_beats_raw)
        pitch_name = freq_to_pitch_name(freq) if freq is not None else None
        events.append((pitch_name, duration_beats, round(velocity, 2)))

    return tempo_bpm, events


def events_to_tune_source(tempo_bpm: float, events, waveform: str = "sine",
                           instrument_name: str = "transcribed",
                           pattern_name: str = "transcribed") -> str:
    lines = [
        "# Auto-transcribed by src/audio_transcribe.py -- APPROXIMATE.",
        "# Monophonic pitch/onset detection only: pitch, timing, and velocity",
        "# are all best-effort guesses meant as a starting point to tune by",
        "# hand, not a finished transcription. Chords/polyphony are not",
        "# detected -- each segment is reported as at most one pitch.",
        f"tempo {tempo_bpm:g}",
        "",
        f"instrument {instrument_name} = {waveform}",
        "",
        f"pattern {pattern_name} {{",
    ]
    for pitch_name, duration_beats, velocity in events:
        dur = _format_beats(duration_beats)
        if pitch_name is None:
            lines.append(f"  rest : {dur}")
        else:
            lines.append(f"  note {pitch_name} : {dur} @ {velocity:g}")
    lines.append("}")
    lines.append("")
    lines.append(f"play {instrument_name} {pattern_name}")
    lines.append("")
    return "\n".join(lines)


def _format_beats(beats: float) -> str:
    """Render a snapped duration as a readable fraction where possible,
    matching how a person would actually write it in Tune source (see
    docs/language/02_LANGUAGE_TUTORIAL.md §2.2) rather than a raw float."""
    fractions = {
        1 / 8: "1/8", 1 / 4: "1/4", 1 / 3: "1/3", 1 / 2: "1/2", 3 / 4: "3/4",
        1: "1", 3 / 2: "3/2", 2: "2", 3: "3", 4: "4",
    }
    for value, text in fractions.items():
        if abs(beats - value) < 1e-6:
            return text
    return f"{beats:g}"


def transcribe_to_tune(path: str, tempo_bpm: float = None, waveform: str = "sine") -> str:
    """Full pipeline: audio file -> Tune DSL source text."""
    resolved_tempo, events = transcribe_to_events(path, tempo_bpm=tempo_bpm, waveform=waveform)
    return events_to_tune_source(resolved_tempo, events, waveform=waveform)