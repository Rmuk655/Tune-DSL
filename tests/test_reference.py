import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest
from semantic import NoteEvent
import reference as ref


def test_render_empty_events():
    out = ref.render([], tempo_bpm=120)
    assert len(out) == 0


def test_render_length_matches_duration():
    events = [NoteEvent(440.0, 0.0, 1.0, "sine")]  # 1 beat @120bpm = 0.5s
    out = ref.render(events, tempo_bpm=120)
    expected_samples = int(0.5 * ref.SAMPLE_RATE)
    assert abs(len(out) - expected_samples) <= 2  # +/- rounding


def test_rest_produces_silence_region():
    events = [
        NoteEvent(440.0, 0.0, 0.25, "sine"),
        NoteEvent(None, 0.25, 0.25, "sine"),
        NoteEvent(440.0, 0.5, 0.25, "sine"),
    ]
    out = ref.render(events, tempo_bpm=120)
    sec_per_beat = 60.0 / 120
    rest_start = int(0.25 * sec_per_beat * ref.SAMPLE_RATE) + 100
    rest_end = int(0.5 * sec_per_beat * ref.SAMPLE_RATE) - 100
    rest_region = out[rest_start:rest_end]
    assert np.max(np.abs(rest_region)) < 1e-6


def test_output_never_clips():
    # a loud chord: several overlapping notes should still stay within [-1, 1]
    events = [
        NoteEvent(440.0, 0.0, 1.0, "square"),
        NoteEvent(550.0, 0.0, 1.0, "square"),
        NoteEvent(660.0, 0.0, 1.0, "square"),
    ]
    out = ref.render(events, tempo_bpm=120)
    assert np.max(np.abs(out)) <= 1.0 + 1e-6


def test_sine_frequency_via_fft():
    freq = 440.0
    events = [NoteEvent(freq, 0.0, 4.0, "sine")]  # long note for FFT resolution
    out = ref.render(events, tempo_bpm=120)
    # trim envelope-affected edges
    n = len(out)
    trimmed = out[int(n * 0.1): int(n * 0.9)]
    spectrum = np.abs(np.fft.rfft(trimmed))
    freqs = np.fft.rfftfreq(len(trimmed), d=1.0 / ref.SAMPLE_RATE)
    peak_freq = freqs[np.argmax(spectrum)]
    assert abs(peak_freq - freq) < 2.0  # within 2 Hz


def test_square_wave_is_bimodal():
    events = [NoteEvent(220.0, 0.0, 2.0, "square")]
    out = ref.render(events, tempo_bpm=120)
    n = len(out)
    trimmed = out[int(n * 0.2): int(n * 0.8)]
    # square wave (after normalization) should sit near its two extremes
    near_extremes = np.mean((np.abs(trimmed) > 0.8))
    assert near_extremes > 0.9


def test_envelope_avoids_clicks_at_note_start():
    events = [NoteEvent(440.0, 0.0, 0.5, "square")]
    out = ref.render(events, tempo_bpm=120)
    # first sample should start near zero due to fade-in, not jump to +/-1
    assert abs(out[0]) < 0.1


def test_beats_to_seconds_basic():
    assert abs(ref.beats_to_seconds(1.0, 120) - 0.5) < 1e-9
    assert abs(ref.beats_to_seconds(2.0, 60) - 2.0) < 1e-9


def test_waveform_sample_shapes():
    phase = np.array([0.0, 0.25, 0.5, 0.75])
    sine = ref.waveform_sample("sine", phase)
    assert abs(sine[0]) < 1e-9        # sin(0) = 0
    assert abs(sine[1] - 1.0) < 1e-9  # sin(pi/2) = 1

    square = ref.waveform_sample("square", phase)
    assert list(square) == [1.0, 1.0, -1.0, -1.0]

    saw = ref.waveform_sample("saw", phase)
    assert abs(saw[0] - (-1.0)) < 1e-9
    assert abs(saw[-1] - 0.5) < 1e-9

    tri = ref.waveform_sample("triangle", phase)
    assert abs(tri[0] - 1.0) < 1e-9    # 2*|2*0-1|-1 = 1
    assert abs(tri[1] - 0.0) < 1e-9    # 2*|2*0.25-1|-1 = 0


def test_unknown_waveform_raises():
    with pytest.raises(ValueError):
        ref.waveform_sample("bogus", np.array([0.0]))


def test_write_wav_header_correct(tmp_path):
    samples = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)
    path = tmp_path / "out.wav"
    ref.write_wav(str(path), samples, sample_rate=44100)

    data = path.read_bytes()
    assert data[0:4] == b"RIFF"
    assert data[8:12] == b"WAVE"
    assert data[12:16] == b"fmt "
    import struct
    num_channels = struct.unpack("<H", data[22:24])[0]
    sample_rate = struct.unpack("<I", data[24:28])[0]
    bits_per_sample = struct.unpack("<H", data[34:36])[0]
    assert num_channels == 1
    assert sample_rate == 44100
    assert bits_per_sample == 16
    assert data[36:40] == b"data"
    data_size = struct.unpack("<I", data[40:44])[0]
    assert data_size == len(samples) * 2  # 16-bit = 2 bytes/sample


def test_write_wav_clips_out_of_range_safely(tmp_path):
    samples = np.array([2.0, -2.0], dtype=np.float32)  # out of [-1,1]
    path = tmp_path / "out.wav"
    ref.write_wav(str(path), samples)  # must not raise / overflow int16
    data = path.read_bytes()
    assert len(data) == 44 + 4  # header + 2 samples * 2 bytes


def test_render_program_mixes_multiple_plays():
    import sys, os as _os
    sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "src"))
    from parser import parse
    from semantic import analyze

    src = (
        "instrument lead = sine\n"
        "instrument bass = square\n"
        "pattern hi { note C5 : 1/4 }\n"
        "pattern lo { note C3 : 1/4 }\n"
        "play lead hi\n"
        "play bass lo\n"
    )
    result = analyze(parse(src))
    out = ref.render_program(result)
    # both patterns are 1/4 beat @ default 120bpm -> same length either way
    solo = ref.render(result.note_events["hi"], result.tempo_bpm)
    assert len(out) == len(solo)
    # mixed output should differ from either solo track (both layered in)
    assert not np.allclose(out, solo)


def test_pulse_waveform_25_percent_duty():
    phase = np.array([0.0, 0.1, 0.24, 0.26, 0.5, 0.9])
    pulse = ref.waveform_sample("pulse", phase)
    assert list(pulse) == [1.0, 1.0, 1.0, -1.0, -1.0, -1.0]


def test_noise_is_deterministic_and_bounded():
    idx = np.arange(1000, dtype=np.int64)
    n1 = ref.waveform_sample("noise", None, idx)
    n2 = ref.waveform_sample("noise", None, idx)
    assert np.array_equal(n1, n2)  # same index -> same output, every time
    assert np.all(n1 >= -1.0) and np.all(n1 <= 1.0)
    assert np.std(n1) > 0.1  # actually varies, not constant


def test_noise_different_indices_differ():
    idx = np.arange(100, dtype=np.int64)
    n = ref.waveform_sample("noise", None, idx)
    assert len(np.unique(n)) > 50  # not degenerate/collapsed


def test_velocity_does_not_crash_mixed_render():
    from semantic import NoteEvent
    mixed = ref.render([
        NoteEvent(440.0, 0.0, 1.0, "sine", velocity=1.0),
        NoteEvent(880.0, 0.0, 1.0, "sine", velocity=0.25),
    ], tempo_bpm=120)
    assert len(mixed) > 0


def test_apply_lowpass_smooths_a_step():
    buf = np.concatenate([np.zeros(100), np.ones(1000)])
    out = ref.apply_lowpass(buf, cutoff_hz=200)
    assert out[99] < 0.1         # still near zero right before the step
    assert out[-1] > 0.9         # settles near 1 after enough samples
    assert 0.0 < out[105] < 1.0  # mid-transition: smoothed, not an instant jump


def test_apply_lowpass_zero_cutoff_is_noop():
    buf = np.array([0.5, -0.3, 0.8])
    out = ref.apply_lowpass(buf, cutoff_hz=0)
    assert np.array_equal(out, buf)


def test_apply_delay_produces_echo():
    buf = np.zeros(1000)
    buf[0] = 1.0  # single impulse
    out = ref.apply_delay(buf, delay_sec=0.01, feedback=0.5)
    delay_samples = int(round(0.01 * ref.SAMPLE_RATE))
    assert out[0] == 1.0
    assert abs(out[delay_samples] - 0.5) < 1e-9  # first echo at 0.5x
    assert len(out) > len(buf)  # tail extends the buffer


def test_apply_effects_chains_in_order():
    buf = np.zeros(2000)
    buf[0] = 1.0
    out = ref.apply_effects(buf, [("lowpass", [500.0]), ("delay", [0.01, 0.3])])
    assert len(out) >= len(buf)
    assert not np.any(np.isnan(out))


def test_apply_highpass_blocks_dc_passes_high_freq():
    # a constant (DC) signal should be attenuated toward zero by a highpass
    buf = np.ones(2000)
    out = ref.apply_highpass(buf, cutoff_hz=500)
    assert abs(out[-1]) < 0.05  # DC component squashed after settling


def test_apply_highpass_zero_cutoff_is_noop():
    buf = np.array([0.5, -0.3, 0.8])
    out = ref.apply_highpass(buf, cutoff_hz=0)
    assert np.array_equal(out, buf)


def test_apply_distortion_compresses_peaks():
    buf = np.array([0.1, 0.5, 0.9, -0.9, 1.0])
    out = ref.apply_distortion(buf, drive=5.0)
    assert np.all(np.abs(out) <= 1.0 + 1e-9)
    assert abs(out[-1] - 1.0) < 1e-9  # peak-preserving: input 1.0 -> output 1.0
    # monotonically increasing (a real soft-clip curve, not scrambled)
    assert out[0] < out[1] < out[2] < out[4]


def test_apply_distortion_higher_drive_saturates_more():
    x = np.array([0.5])
    mild = ref.apply_distortion(x, drive=1.0)
    heavy = ref.apply_distortion(x, drive=10.0)
    # higher drive pushes mid-level values closer to the +/-1 ceiling
    assert heavy[0] > mild[0]


def test_apply_distortion_zero_drive_is_noop():
    buf = np.array([0.5, -0.3])
    out = ref.apply_distortion(buf, drive=0)
    assert np.array_equal(out, buf)


def test_apply_tremolo_modulates_amplitude():
    rate_hz = 5.0
    duration_sec = 2.0 / rate_hz  # exactly 2 full LFO cycles -> hits both extremes
    n = int(duration_sec * ref.SAMPLE_RATE)
    buf = np.ones(n)
    out = ref.apply_tremolo(buf, rate_hz=rate_hz, depth=1.0)
    assert np.std(out) > 0.1
    assert np.max(out) > 0.9   # near peak (LFO trough at 1-depth*0=1)
    assert np.min(out) < 0.1   # near zero (LFO peak at 1-depth*1=0)


def test_apply_tremolo_zero_depth_is_noop():
    buf = np.array([0.5, -0.3, 0.8])
    out = ref.apply_tremolo(buf, rate_hz=5.0, depth=0.0)
    assert np.array_equal(out, buf)


def test_render_applies_effects_end_to_end():
    from semantic import NoteEvent
    events = [NoteEvent(440.0, 0.0, 1.0, "sine", velocity=1.0)]
    plain = ref.render(events, tempo_bpm=120)
    with_fx = ref.render(events, tempo_bpm=120, effects=[("lowpass", [300.0])])
    assert len(with_fx) >= len(plain)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))