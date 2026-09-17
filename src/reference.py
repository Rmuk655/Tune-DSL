"""
Tune DSL — reference synthesizer (Python/numpy).

This is intentionally the simplest-possible correct implementation of
"note events -> samples". It exists to be the ground truth we numerically
diff the generated C++ output against, so a C++ bug that compiles and
runs but produces subtly wrong audio doesn't slip through silently.

No cleverness here on purpose: straightforward per-sample loops via
numpy vectorized ops, one waveform at a time, summed into a buffer.
"""

import numpy as np

SAMPLE_RATE = 44100
WAVEFORMS = ("sine", "square", "saw", "triangle", "pulse", "noise")


def _hash_u32(x: np.ndarray) -> np.ndarray:
    """Deterministic avalanche hash (triple32), used for the noise waveform.
    Same algorithm and same uint32 wraparound semantics must be replicated
    exactly in codegen.py's C++ output for the two backends to match.
    """
    x = x.astype(np.uint32)
    x = (x ^ (x >> np.uint32(16))) & np.uint32(0xFFFFFFFF)
    x = (x * np.uint32(0x7feb352d)) & np.uint32(0xFFFFFFFF)
    x = (x ^ (x >> np.uint32(15))) & np.uint32(0xFFFFFFFF)
    x = (x * np.uint32(0x846ca68b)) & np.uint32(0xFFFFFFFF)
    x = (x ^ (x >> np.uint32(16))) & np.uint32(0xFFFFFFFF)
    return x


def waveform_sample(waveform: str, phase: np.ndarray, idx: np.ndarray = None) -> np.ndarray:
    """phase is in [0, 1) per-sample, representing position within one cycle.
    idx (absolute sample index) is only used by "noise", which ignores phase."""
    if waveform == "sine":
        return np.sin(2 * np.pi * phase)
    if waveform == "square":
        return np.where(phase < 0.5, 1.0, -1.0)
    if waveform == "saw":
        return 2.0 * phase - 1.0
    if waveform == "triangle":
        return 2.0 * np.abs(2.0 * phase - 1.0) - 1.0
    if waveform == "pulse":  # fixed 25% duty cycle
        return np.where(phase < 0.25, 1.0, -1.0)
    if waveform == "noise":
        h = _hash_u32(idx)
        return (h.astype(np.float64) / 4294967295.0) * 2.0 - 1.0
    raise ValueError(f"unknown waveform {waveform!r}")


def beats_to_seconds(beats: float, tempo_bpm: float) -> float:
    # 1 beat = 1 quarter note by convention; tempo_bpm = quarter notes / min
    return beats * (60.0 / tempo_bpm)


def apply_lowpass(buffer: np.ndarray, cutoff_hz: float, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Simple one-pole IIR low-pass filter: y[n] = y[n-1] + a*(x[n]-y[n-1]).
    Inherently sequential (each output depends on the previous), so this
    can't be vectorized with numpy ops -- a plain loop is used, matching
    exactly what the C++ side does (same recurrence, same order)."""
    if cutoff_hz <= 0 or len(buffer) == 0:
        return buffer
    dt = 1.0 / sample_rate
    rc = 1.0 / (2.0 * np.pi * cutoff_hz)
    alpha = dt / (rc + dt)
    out = np.empty_like(buffer)
    prev = 0.0
    for i in range(len(buffer)):
        prev = prev + alpha * (buffer[i] - prev)
        out[i] = prev
    return out


def apply_delay(buffer: np.ndarray, delay_sec: float, feedback: float, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Feedback delay line: y[n] = x[n] + feedback*y[n - delay_samples].
    Extends the buffer to let the delay tail ring out."""
    delay_samples = int(round(delay_sec * sample_rate))
    if delay_samples <= 0 or len(buffer) == 0:
        return buffer
    tail = delay_samples * 4  # let a few repeats ring out audibly
    out = np.zeros(len(buffer) + tail, dtype=np.float64)
    for i in range(len(out)):
        x = buffer[i] if i < len(buffer) else 0.0
        fb = out[i - delay_samples] * feedback if i >= delay_samples else 0.0
        out[i] = x + fb
    return out


def apply_highpass(buffer: np.ndarray, cutoff_hz: float, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """One-pole high-pass: y[n] = alpha*(y[n-1] + x[n] - x[n-1]).
    Sequential recurrence, same reasoning as apply_lowpass -- a plain loop,
    matched exactly by the C++ side."""
    if cutoff_hz <= 0 or len(buffer) == 0:
        return buffer
    dt = 1.0 / sample_rate
    rc = 1.0 / (2.0 * np.pi * cutoff_hz)
    alpha = rc / (rc + dt)
    out = np.empty_like(buffer)
    prev_y = 0.0
    prev_x = buffer[0]
    for i in range(len(buffer)):
        x = buffer[i]
        prev_y = alpha * (prev_y + x - prev_x)
        out[i] = prev_y
        prev_x = x
    return out


def apply_distortion(buffer: np.ndarray, drive: float) -> np.ndarray:
    """Soft-clipping saturation via tanh, normalized so an input at exactly
    +/-1 maps to output +/-1 (peak-preserving soft clip). Purely elementwise
    (no history needed), so -- unlike lowpass/delay/highpass -- this
    vectorizes trivially and so does its C++ equivalent (no sequential
    dependency between samples)."""
    if drive <= 0 or len(buffer) == 0:
        return buffer
    norm = np.tanh(drive)
    if norm < 1e-9:
        return buffer
    return np.tanh(drive * buffer) / norm


def apply_tremolo(buffer: np.ndarray, rate_hz: float, depth: float, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Amplitude modulation by a slow sine LFO: y[n] = x[n] * (1 - depth*(0.5+0.5*sin(2*pi*rate*t))).
    depth=0 is a no-op, depth=1 fully pulses down to silence at the LFO's
    trough. Elementwise like distortion -- no sequential dependency."""
    if rate_hz <= 0 or depth <= 0 or len(buffer) == 0:
        return buffer
    depth = min(depth, 1.0)
    t = np.arange(len(buffer), dtype=np.float64) / sample_rate
    lfo = 0.5 + 0.5 * np.sin(2.0 * np.pi * rate_hz * t)
    return buffer * (1.0 - depth * lfo)


def apply_effects(buffer: np.ndarray, effects, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    for name, args in effects:
        if name == "lowpass":
            buffer = apply_lowpass(buffer, args[0], sample_rate)
        elif name == "delay":
            buffer = apply_delay(buffer, args[0], args[1], sample_rate)
        elif name == "highpass":
            buffer = apply_highpass(buffer, args[0], sample_rate)
        elif name == "distortion":
            buffer = apply_distortion(buffer, args[0])
        elif name == "tremolo":
            buffer = apply_tremolo(buffer, args[0], args[1], sample_rate)
        else:
            raise ValueError(f"unknown effect {name!r}")
    return buffer


def render(note_events, tempo_bpm: float, sample_rate: int = SAMPLE_RATE, effects=None) -> np.ndarray:
    """note_events: list of NoteEvent(freq_hz, start_beat, duration_beats, waveform, velocity).
    Returns a 1-D float32 numpy array of samples in [-1, 1] (post-normalization).
    """
    if not note_events:
        return np.zeros(0, dtype=np.float32)

    total_beats = max(ev.start_beat + ev.duration_beats for ev in note_events)
    total_sec = beats_to_seconds(total_beats, tempo_bpm)
    total_samples = int(np.ceil(total_sec * sample_rate)) + 1
    buffer = np.zeros(total_samples, dtype=np.float64)

    for ev in note_events:
        if ev.freq_hz is None:
            continue  # rest: contributes silence, nothing to add
        start_sec = beats_to_seconds(ev.start_beat, tempo_bpm)
        dur_sec = beats_to_seconds(ev.duration_beats, tempo_bpm)
        start_sample = int(round(start_sec * sample_rate))
        n = int(round(dur_sec * sample_rate))
        if n <= 0:
            continue
        t = np.arange(n, dtype=np.float64) / sample_rate

        slide_from = getattr(ev, "slide_from_freq", None)
        if slide_from is not None:
            # Frequency ramps linearly from f1 to f2 over the note's
            # actual duration T: f(t) = f1 + (f2-f1)*(t/T). Phase is the
            # PHYSICAL integral of frequency over time, not frequency
            # itself times t (that shortcut would silently produce a
            # discontinuous, audibly wrong glide) --
            #   phase(t) = integral_0^t f(u) du
            #            = f1*t + (f2-f1)*t^2/(2T)
            f1 = slide_from
            f2 = ev.freq_hz
            T = n / sample_rate  # actual rendered duration, matches sample count exactly
            phase_raw = f1 * t + (f2 - f1) * (t * t) / (2.0 * T)
            phase = np.mod(phase_raw, 1.0)
        else:
            phase = np.mod(ev.freq_hz * t, 1.0)

        idx = start_sample + np.arange(n, dtype=np.int64)
        wave = waveform_sample(ev.waveform, phase, idx)

        # envelope: per-instrument attack/release override if given,
        # otherwise the default short 5ms fade (click prevention). Each
        # side is independently clamped to half the note length.
        default_fade = int(0.005 * sample_rate)
        attack_sec = getattr(ev, "attack_sec", None)
        release_sec = getattr(ev, "release_sec", None)
        attack_samples = int(round(attack_sec * sample_rate)) if attack_sec is not None else default_fade
        release_samples = int(round(release_sec * sample_rate)) if release_sec is not None else default_fade
        attack_samples = min(attack_samples, n // 2)
        release_samples = min(release_samples, n // 2)

        env = np.ones(n, dtype=np.float64)
        if attack_samples > 0:
            env[:attack_samples] = np.linspace(0.0, 1.0, attack_samples)
        if release_samples > 0:
            env[-release_samples:] = np.linspace(1.0, 0.0, release_samples)
        wave = wave * env

        velocity = getattr(ev, "velocity", 1.0)
        wave = wave * velocity

        end_sample = start_sample + n
        if end_sample > len(buffer):
            end_sample = len(buffer)
            wave = wave[: end_sample - start_sample]
        buffer[start_sample:end_sample] += wave

    if effects:
        buffer = apply_effects(buffer, effects, sample_rate)

    peak = np.max(np.abs(buffer)) if buffer.size else 0.0
    if peak > 1e-9:
        buffer = buffer / peak * 0.95  # normalize, leave a little headroom

    return buffer.astype(np.float32)


def render_program(result, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Mix every `play` statement's note events into a single timeline.
    Multiple `play` lines all start at beat 0 and overlap (layered),
    matching how you'd expect several instruments playing together.
    """
    all_events = []
    for _instrument, pattern in result.plays:
        all_events.extend(result.note_events[pattern])
    effects = getattr(result, "effects", None)
    return render(all_events, result.tempo_bpm, sample_rate, effects=effects)


def write_wav(path: str, samples: np.ndarray, sample_rate: int = SAMPLE_RATE):
    """Hand-rolled 16-bit PCM mono WAV writer (no external deps beyond numpy)."""
    import struct

    pcm = np.clip(samples, -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype(np.int16)
    data_bytes = pcm16.tobytes()

    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8

    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + len(data_bytes)))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))  # PCM fmt chunk size
        f.write(struct.pack("<H", 1))   # PCM format
        f.write(struct.pack("<H", num_channels))
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", byte_rate))
        f.write(struct.pack("<H", block_align))
        f.write(struct.pack("<H", bits_per_sample))
        f.write(b"data")
        f.write(struct.pack("<I", len(data_bytes)))
        f.write(data_bytes)