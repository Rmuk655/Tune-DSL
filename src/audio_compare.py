"""
Tune DSL -- comparing rendered audio ("actual") against a reference
recording ("expected").

Honest scope, stated up front the same way src/chordsheet.py states
its own scope: this module computes a small set of *numeric similarity
heuristics* (waveform correlation after alignment, RMS error, spectral
correlation). It is not a perceptual/musical-accuracy model and does
not claim to judge whether a rendering "sounds like" the reference to
a human listener -- pitch, timing, and timbre differences all move
these numbers, and there is no single "correct" pass/fail threshold.
Treat the report as a diagnostic aid (did this change make the render
numerically closer to the reference, or further away?), not a grade.
"""

import numpy as np

from audio_io import load_wav_mono, resample_linear


class AudioCompareError(Exception):
    pass


def _align_by_cross_correlation(expected: np.ndarray, actual: np.ndarray, max_shift: int):
    """Find the sample offset that best aligns `actual` to `expected`,
    via FFT-based cross-correlation, searched within +/- max_shift.

    Returns `offset` such that `expected[offset:]` lines up with
    `actual[:]` (see compute_metrics's use of it just below this
    function): a POSITIVE offset means actual's content starts
    *earlier* than expected's (actual leads / expected lags); a
    NEGATIVE offset means actual's content starts *later* than
    expected's (actual lags / expected leads) -- e.g. if `actual` is
    `expected` with silence prepended, offset comes out negative, with
    magnitude equal to how much silence was prepended."""
    n = 1
    total_len = len(expected) + len(actual)
    while n < total_len:
        n *= 2
    fa = np.fft.rfft(expected, n)
    fb = np.fft.rfft(actual, n)
    corr = np.fft.irfft(fa * np.conj(fb), n)
    # corr[k] for k in [0, max_shift] and [n-max_shift, n) covers lags
    # in [-max_shift, max_shift]
    lags = list(range(0, max_shift + 1)) + list(range(n - max_shift, n))
    best_lag, best_val = 0, -np.inf
    for k in lags:
        if corr[k] > best_val:
            best_val = corr[k]
            best_lag = k if k <= max_shift else k - n
    return best_lag


def compute_metrics(expected: np.ndarray, actual: np.ndarray, sample_rate: int) -> dict:
    """Compare two mono float32 buffers at the SAME sample rate.
    See module docstring for what these numbers do and don't mean."""
    if len(expected) == 0 or len(actual) == 0:
        raise AudioCompareError("cannot compare an empty audio buffer")

    duration_expected = len(expected) / sample_rate
    duration_actual = len(actual) / sample_rate

    max_shift = min(sample_rate // 2, max(len(expected), len(actual)) - 1)
    offset = _align_by_cross_correlation(expected, actual, max_shift) if max_shift > 0 else 0

    # overlap the two buffers at the found offset
    if offset >= 0:
        e = expected[offset:]
        a = actual[: len(e)]
    else:
        a = actual[-offset:]
        e = expected[: len(a)]
    n = min(len(e), len(a))
    e, a = e[:n], a[:n]

    if n < 2:
        waveform_correlation = 0.0
        rms_error = 1.0
    else:
        e_c = e - e.mean()
        a_c = a - a.mean()
        denom = np.sqrt((e_c ** 2).sum() * (a_c ** 2).sum())
        waveform_correlation = float((e_c * a_c).sum() / denom) if denom > 1e-12 else 0.0
        e_peak = np.abs(e).max()
        a_peak = np.abs(a).max()
        peak = max(e_peak, a_peak, 1e-9)
        rms_error = float(np.sqrt(((e / peak - a / peak) ** 2).mean()))

    # spectral correlation: compare average magnitude spectra over the
    # full (un-overlapped) signals, so it's meaningful even when timing
    # alignment is poor -- this is what mainly captures "similar pitch
    # content / timbre" independent of exact phase or onset timing.
    def avg_spectrum(x, n_fft=4096, hop=2048):
        if len(x) < n_fft:
            x = np.pad(x, (0, n_fft - len(x)))
        window = np.hanning(n_fft)
        mags = []
        for start in range(0, len(x) - n_fft + 1, hop):
            frame = x[start:start + n_fft] * window
            mags.append(np.abs(np.fft.rfft(frame)))
        if not mags:
            mags = [np.abs(np.fft.rfft(x[:n_fft] * window))]
        return np.mean(mags, axis=0)

    spec_e = avg_spectrum(expected)
    spec_a = avg_spectrum(actual)
    n_bins = min(len(spec_e), len(spec_a))
    se, sa = spec_e[:n_bins], spec_a[:n_bins]
    se_c, sa_c = se - se.mean(), sa - sa.mean()
    denom = np.sqrt((se_c ** 2).sum() * (sa_c ** 2).sum())
    spectral_correlation = float((se_c * sa_c).sum() / denom) if denom > 1e-12 else 0.0

    # A single combined heuristic score in [0, 100], for a quick glance --
    # equal-weighted average of waveform and spectral correlation (each
    # already in roughly [-1, 1]; negative correlation clamped to 0 since
    # "anti-correlated" is not meaningfully "50% similar").
    similarity_score = 100.0 * max(0.0, (max(0.0, waveform_correlation) + max(0.0, spectral_correlation)) / 2.0)

    return {
        "duration_expected_sec": duration_expected,
        "duration_actual_sec": duration_actual,
        "duration_diff_sec": duration_actual - duration_expected,
        "alignment_offset_sec": offset / sample_rate,
        "waveform_correlation": waveform_correlation,
        "rms_error": rms_error,
        "spectral_correlation": spectral_correlation,
        "similarity_score": similarity_score,
    }


def compare_files(expected_path: str, actual_path: str) -> dict:
    """Load two WAV files (any common sample rate/bit depth -- see
    audio_io.py) and compare them. Resamples the lower-rate file up to
    match, via simple linear interpolation, if the two differ."""
    expected, sr_e = load_wav_mono(expected_path)
    actual, sr_a = load_wav_mono(actual_path)
    if sr_e != sr_a:
        target = max(sr_e, sr_a)
        expected = resample_linear(expected, sr_e, target)
        actual = resample_linear(actual, sr_a, target)
        sample_rate = target
    else:
        sample_rate = sr_e
    return compute_metrics(expected, actual, sample_rate)


def render_report(metrics: dict, expected_path: str = "expected", actual_path: str = "actual") -> str:
    """Human-readable text report, for the CLI."""
    lines = [
        f"Comparing {actual_path!r} (actual) against {expected_path!r} (expected)",
        "-" * 60,
        f"  duration:            expected {metrics['duration_expected_sec']:.2f}s"
        f"   actual {metrics['duration_actual_sec']:.2f}s"
        f"   (diff {metrics['duration_diff_sec']:+.2f}s)",
        f"  alignment offset:    {metrics['alignment_offset_sec']:+.3f}s"
        f"  (+ = actual leads/starts earlier, - = actual lags/starts later)",
        f"  waveform correlation:  {metrics['waveform_correlation']:+.3f}  (1.0 = identical shape, after alignment)",
        f"  spectral correlation:  {metrics['spectral_correlation']:+.3f}  (1.0 = same pitch/timbre content on average)",
        f"  normalized RMS error:  {metrics['rms_error']:.3f}   (0.0 = identical loudness-normalized signal)",
        "-" * 60,
        f"  similarity score:    {metrics['similarity_score']:.1f} / 100"
        f"   (heuristic -- see src/audio_compare.py's module docstring)",
    ]
    return "\n".join(lines)


def plot_comparison(expected: np.ndarray, actual: np.ndarray, sample_rate: int, out_path: str):
    """Optional: waveform-overlay + spectrogram-difference PNG. Only
    runs if matplotlib is installed -- this project has no other use
    for a plotting dependency, so it's imported lazily and this
    function is simply skipped (returning False) if it's absent,
    rather than making matplotlib a hard dependency of the project."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    n = min(len(expected), len(actual))
    t = np.arange(n) / sample_rate

    fig, axes = plt.subplots(2, 1, figsize=(10, 6))
    axes[0].plot(t, expected[:n], label="expected", alpha=0.7, linewidth=0.6)
    axes[0].plot(t, actual[:n], label="actual", alpha=0.7, linewidth=0.6)
    axes[0].set_title("Waveform overlay")
    axes[0].set_xlabel("seconds")
    axes[0].legend()

    n_fft = 1024
    hop = 256

    def spectrogram(x):
        window = np.hanning(n_fft)
        frames = []
        for start in range(0, max(1, len(x) - n_fft), hop):
            frame = x[start:start + n_fft]
            if len(frame) < n_fft:
                frame = np.pad(frame, (0, n_fft - len(frame)))
            frames.append(np.abs(np.fft.rfft(frame * window)))
        return np.array(frames).T if frames else np.zeros((n_fft // 2 + 1, 1))

    spec_e = spectrogram(expected[:n])
    spec_a = spectrogram(actual[:n])
    m = min(spec_e.shape[1], spec_a.shape[1])
    diff = np.abs(np.log1p(spec_e[:, :m]) - np.log1p(spec_a[:, :m]))
    im = axes[1].imshow(diff, aspect="auto", origin="lower", cmap="magma")
    axes[1].set_title("Spectral difference (|log-magnitude expected - actual|, brighter = more different)")
    axes[1].set_xlabel("frame")
    axes[1].set_ylabel("frequency bin")
    fig.colorbar(im, ax=axes[1])

    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return True