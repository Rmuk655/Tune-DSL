import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest
from audio_transcribe import (
    transcribe_to_events, transcribe_to_tune, events_to_tune_source,
    TranscribeError, _snap_duration_beats, _format_beats,
)
from reference import render_program, write_wav
from semantic import analyze
from parser import parse
from pitch import midi_to_pitch_name, freq_to_pitch_name, freq_to_midi


def _render_tmp_wav(tmp_path, source, name="out.wav"):
    result = analyze(parse(source))
    samples = render_program(result)
    path = os.path.join(tmp_path, name)
    write_wav(path, samples)
    return path


def test_midi_to_pitch_name_round_trips_c4():
    assert midi_to_pitch_name(60) == "C4"


def test_freq_to_pitch_name_a4():
    assert freq_to_pitch_name(440.0) == "A4"


def test_freq_to_midi_matches_known_value():
    assert freq_to_midi(440.0) == 69


def test_snap_duration_picks_nearest_candidate():
    assert _snap_duration_beats(0.24) == 1 / 4
    assert _snap_duration_beats(0.98) == 1


def test_format_beats_uses_readable_fractions():
    assert _format_beats(1 / 4) == "1/4"
    assert _format_beats(2) == "2"


def test_transcribe_a_single_sustained_note(tmp_path):
    source = """
    tempo 120
    instrument lead = sine
    pattern p { note A4 : 4 }
    play lead p
    """
    path = _render_tmp_wav(tmp_path, source)
    tempo, events = transcribe_to_events(path, tempo_bpm=120)
    pitched = [e for e in events if e[0] is not None]
    assert len(pitched) >= 1
    # a pure 440Hz sine should be detected close to A4 -- allow the
    # detector to land on the exact pitch or an octave-related neighbor,
    # since autocorrelation pitch detection is inherently approximate
    assert pitched[0][0] in ("A4", "A3", "A5")


def test_transcribe_too_short_audio_raises(tmp_path):
    silence = np.zeros(100, dtype=np.float32)
    path = os.path.join(tmp_path, "tiny.wav")
    write_wav(path, silence)
    with pytest.raises(TranscribeError):
        transcribe_to_events(path)


def test_transcribe_to_tune_produces_parseable_source(tmp_path):
    source = """
    tempo 100
    instrument lead = sine
    pattern p {
      note C4 : 1/2
      note E4 : 1/2
      note G4 : 1
    }
    play lead p
    """
    path = _render_tmp_wav(tmp_path, source)
    tune_source = transcribe_to_tune(path)
    # must be valid Tune DSL, even if the pitches/timing are approximate
    program = parse(tune_source)
    result = analyze(program)
    assert result.plays


def test_events_to_tune_source_includes_honesty_header():
    src = events_to_tune_source(120, [("C4", 1, 0.8)])
    assert "APPROXIMATE" in src
    assert "tempo 120" in src
    assert "note C4 : 1 @ 0.8" in src


def test_events_to_tune_source_renders_rests():
    src = events_to_tune_source(120, [(None, 1 / 2, 0.0), ("C4", 1, 0.8)])
    assert "rest : 1/2" in src