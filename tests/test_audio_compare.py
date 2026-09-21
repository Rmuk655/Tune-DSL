import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest
from audio_compare import compute_metrics, compare_files, render_report, AudioCompareError
from reference import render_program, write_wav, SAMPLE_RATE
from semantic import analyze
from parser import parse


def _render_tmp_wav(tmp_path, source, name="out.wav"):
    result = analyze(parse(source))
    samples = render_program(result)
    path = os.path.join(tmp_path, name)
    write_wav(path, samples)
    return path


SIMPLE_SONG = """
tempo 120
instrument lead = sine
pattern melody {
  note C4 : 1/2
  note E4 : 1/2
  note G4 : 1
}
play lead melody
"""

DIFFERENT_SONG = """
tempo 120
instrument lead = square
pattern melody {
  note A2 : 1
  note B2 : 1
}
play lead melody
"""


def test_identical_files_score_near_100(tmp_path):
    path = _render_tmp_wav(tmp_path, SIMPLE_SONG)
    metrics = compare_files(path, path)
    assert metrics["similarity_score"] > 99.0
    assert metrics["waveform_correlation"] > 0.99
    assert metrics["rms_error"] < 0.01


def test_very_different_files_score_much_lower(tmp_path):
    path_a = _render_tmp_wav(tmp_path, SIMPLE_SONG, "a.wav")
    path_b = _render_tmp_wav(tmp_path, DIFFERENT_SONG, "b.wav")
    metrics = compare_files(path_a, path_b)
    same = compare_files(path_a, path_a)
    assert metrics["similarity_score"] < same["similarity_score"]


def test_duration_diff_reported(tmp_path):
    short = """
    tempo 120
    instrument lead = sine
    pattern p { note C4 : 1 }
    play lead p
    """
    long = """
    tempo 120
    instrument lead = sine
    pattern p { note C4 : 4 }
    play lead p
    """
    path_a = _render_tmp_wav(tmp_path, short, "short.wav")
    path_b = _render_tmp_wav(tmp_path, long, "long.wav")
    metrics = compare_files(path_a, path_b)
    assert metrics["duration_diff_sec"] > 0


def test_empty_buffer_raises():
    with pytest.raises(AudioCompareError):
        compute_metrics(np.array([]), np.array([1.0, 2.0]), SAMPLE_RATE)


def test_render_report_contains_key_fields(tmp_path):
    path = _render_tmp_wav(tmp_path, SIMPLE_SONG)
    metrics = compare_files(path, path)
    report = render_report(metrics, "expected.wav", "actual.wav")
    assert "similarity score" in report
    assert "expected.wav" in report
    assert "actual.wav" in report


def test_time_shifted_copy_still_scores_high_after_alignment(tmp_path):
    # a pure delay should be recoverable by the cross-correlation alignment
    # step -- this is the whole point of aligning before scoring. `actual`
    # here has 0.1s of silence prepended, so it lags `expected`, which
    # comes out as a NEGATIVE offset under this module's sign convention
    # (see _align_by_cross_correlation's docstring in src/audio_compare.py).
    path = _render_tmp_wav(tmp_path, SIMPLE_SONG)
    samples, sr = __import__("audio_io").load_wav_mono(path)
    padded = np.concatenate([np.zeros(int(0.1 * sr), dtype=np.float32), samples])
    shifted_path = os.path.join(tmp_path, "shifted.wav")
    write_wav(shifted_path, padded)
    metrics = compare_files(path, shifted_path)
    assert metrics["waveform_correlation"] > 0.95
    assert abs(metrics["alignment_offset_sec"] - (-0.1)) < 0.01