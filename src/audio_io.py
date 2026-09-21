"""
Tune DSL -- WAV file *reading*.

Every WAV file Tune itself produces is written by hand-rolled writers
(src/reference.py, src/codegen.py, src/codegen_mlir.py) that only ever
emit 16-bit PCM mono -- there was never a need to read arbitrary WAV
files back in, so no reader existed.

audio_compare.py and audio_transcribe.py both need to read audio that
did NOT come from Tune (a user's reference recording, an uploaded
sample) -- which may be mono or stereo, and 8/16/24/32-bit PCM, or
32-bit float. That's a wider format space than the project's own
writers ever produce, so this module uses Python's standard-library
`wave` module (which already parses the general RIFF/WAVE structure
correctly) rather than re-deriving that parsing by hand a second time.
This mirrors the project's own stated principle (see
docs/language/00_WHITEPAPER.md, "prefer standard infrastructure where
Tune isn't the one defining the format") -- Tune's own file *formats*
(.tune source, its WAV output, its MIDI output) are hand-rolled on
purpose; parsing *someone else's* WAV file is not one of those formats.
"""

import struct
import wave

import numpy as np


class AudioReadError(Exception):
    pass


def load_wav_mono(path: str):
    """Read a WAV file (any common PCM/float sub-format, mono or
    stereo) and return (samples, sample_rate).

    samples: 1-D float32 numpy array, values in [-1, 1], mono (stereo
             input is averaged down to mono -- Tune itself has no
             stereo concept; see docs/language/05_LANGUAGE_EVOLUTION.md).
    sample_rate: int, Hz.
    """
    try:
        with wave.open(path, "rb") as w:
            n_channels = w.getnchannels()
            sample_width = w.getsampwidth()
            sample_rate = w.getframerate()
            n_frames = w.getnframes()
            raw = w.readframes(n_frames)
    except wave.Error as e:
        raise AudioReadError(f"could not read {path!r} as a WAV file: {e}")
    except FileNotFoundError:
        raise AudioReadError(f"file not found: {path!r}")

    if sample_width == 1:
        # WAV 8-bit PCM is stored unsigned, centered at 128
        data = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
        samples = (data - 128.0) / 128.0
    elif sample_width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32)
        samples = data / 32768.0
    elif sample_width == 3:
        # 24-bit PCM has no native numpy dtype -- unpack 3-byte little-endian
        # signed ints by hand.
        n = len(raw) // 3
        ints = np.zeros(n, dtype=np.int32)
        for i in range(n):
            b = raw[i * 3: i * 3 + 3]
            val = b[0] | (b[1] << 8) | (b[2] << 16)
            if val & 0x800000:
                val -= 0x1000000
            ints[i] = val
        samples = ints.astype(np.float32) / 8388608.0
    elif sample_width == 4:
        # Could be 32-bit int PCM or 32-bit float; WAV's own header
        # distinguishes these via the format tag, which the `wave` module
        # does not expose. Heuristic: treat as int32 PCM (the common case
        # for 32-bit WAV) -- IEEE-float WAV is rare enough in practice
        # that this project does not attempt to auto-detect it.
        data = np.frombuffer(raw, dtype="<i4").astype(np.float64)
        samples = (data / 2147483648.0).astype(np.float32)
    else:
        raise AudioReadError(f"unsupported WAV sample width: {sample_width * 8}-bit")

    if n_channels > 1:
        samples = samples.reshape(-1, n_channels).mean(axis=1).astype(np.float32)
    elif n_channels < 1:
        raise AudioReadError(f"WAV file {path!r} reports {n_channels} channels")

    return samples, sample_rate


def resample_linear(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Simple linear-interpolation resampler -- adequate for comparison/
    transcription purposes (both are already approximate, correlation-
    or heuristic-based operations), not intended as a high-fidelity
    resampler for audio production use."""
    if src_rate == dst_rate or len(samples) == 0:
        return samples
    duration = len(samples) / src_rate
    n_dst = max(1, int(round(duration * dst_rate)))
    src_x = np.arange(len(samples)) / src_rate
    dst_x = np.arange(n_dst) / dst_rate
    return np.interp(dst_x, src_x, samples).astype(np.float32)