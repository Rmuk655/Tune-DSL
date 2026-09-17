import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from chordsheet import parse_chordsheet, chordsheet_to_tune, ChordSheetError, INSTRUMENT_DEFAULTS
from parser import parse
from semantic import analyze
import reference as ref


def test_parse_simple_progression():
    text = "C G Am F\n"
    tempo, entries = parse_chordsheet(text)
    assert tempo is None
    assert entries == [("C", 4), ("G", 4), ("Am", 4), ("F", 4)]


def test_parse_with_tempo_directive():
    text = "tempo 96\nC G\n"
    tempo, entries = parse_chordsheet(text)
    assert tempo == 96.0
    assert entries == [("C", 4), ("G", 4)]


def test_parse_with_custom_beats_per_chord():
    text = "beats_per_chord 2\nC G\n"
    tempo, entries = parse_chordsheet(text)
    assert entries == [("C", 2), ("G", 2)]


def test_parse_explicit_beat_override():
    text = "C:2 G:1 Am:3\n"
    _, entries = parse_chordsheet(text)
    assert entries == [("C", 2), ("G", 1), ("Am", 3)]


def test_parse_bar_repeat():
    text = "beats_per_chord 4\nC*2 G\n"
    _, entries = parse_chordsheet(text)
    assert entries == [("C", 4), ("C", 4), ("G", 4)]


def test_parse_comments_and_blank_lines_ignored():
    text = "# this is a comment\n\nC G\n# another comment\nAm F\n"
    _, entries = parse_chordsheet(text)
    assert entries == [("C", 4), ("G", 4), ("Am", 4), ("F", 4)]


def test_parse_multiple_lines_concatenate():
    text = "C G\nAm F\n"
    _, entries = parse_chordsheet(text)
    assert len(entries) == 4


def test_parse_does_not_validate_chord_symbols():
    # parse_chordsheet only tokenizes; chord validity is chord_theory's
    # job, checked later by chordsheet_to_tune -- confirm that division
    # of responsibility rather than assuming premature validation
    tempo, entries = parse_chordsheet("C notachord\n")
    assert entries == [("C", 4), ("notachord", 4)]


def test_parse_no_chords_at_all():
    tempo, entries = parse_chordsheet("tempo 100\n")
    assert entries == []


# -- chordsheet_to_tune: converter correctness --

def test_convert_produces_parseable_tune_source():
    text = "tempo 100\nC G Am F\n"
    tune_src = chordsheet_to_tune(text, "guitar")
    program = parse(tune_src)  # must not raise
    result = analyze(program)  # must not raise
    assert result.tempo_bpm == 100.0
    assert "guitar" in result.instruments
    assert result.instruments["guitar"] == "pulse"


def test_convert_unknown_instrument_raises():
    with pytest.raises(ChordSheetError):
        chordsheet_to_tune("C G\n", "kazoo")


def test_convert_empty_chordsheet_raises():
    with pytest.raises(ChordSheetError):
        chordsheet_to_tune("tempo 100\n", "guitar")


def test_convert_bad_chord_symbol_raises_chordsheeterror():
    with pytest.raises(ChordSheetError):
        chordsheet_to_tune("Hxyz G\n", "guitar")


def test_all_instrument_presets_produce_valid_tune(tmp_path):
    text = "tempo 100\nC G Am F\n"
    for instrument_key in INSTRUMENT_DEFAULTS:
        tune_src = chordsheet_to_tune(text, instrument_key)
        program = parse(tune_src)
        result = analyze(program)
        events = result.note_events[f"{instrument_key}_pattern"]
        assert len(events) > 0, instrument_key


def test_bass_instrument_plays_root_only_not_full_chord():
    text = "C\n"
    tune_src = chordsheet_to_tune(text, "bass")
    result = analyze(parse(tune_src))
    events = result.note_events["bass_pattern"]
    assert len(events) == 1  # just the root note, not a 3-note chord


def test_non_bass_instrument_plays_full_chord():
    text = "C\n"
    tune_src = chordsheet_to_tune(text, "guitar")
    result = analyze(parse(tune_src))
    events = result.note_events["guitar_pattern"]
    assert len(events) == 3  # full major triad


def test_converted_tune_actually_renders_audio():
    text = "tempo 120\nC G Am F\n"
    tune_src = chordsheet_to_tune(text, "keyboard")
    result = analyze(parse(tune_src))
    samples = ref.render_program(result)
    assert len(samples) > 0
    import numpy as np
    assert np.max(np.abs(samples)) > 0  # not silent


def test_timing_matches_specified_beats():
    text = "tempo 120\nC:2 G:1 Am:1\n"
    tune_src = chordsheet_to_tune(text, "guitar")
    result = analyze(parse(tune_src))
    events = result.note_events["guitar_pattern"]
    # 3 notes per chord (major triad), starting beats should reflect 2,1,1 durations
    starts = sorted(set(ev.start_beat for ev in events))
    assert starts == [0.0, 2.0, 3.0]


def test_new_indian_instruments_present():
    for key in ["harmonium", "santoor", "sarangi", "shehnai", "synth", "tabla"]:
        assert key in INSTRUMENT_DEFAULTS


def test_tabla_produces_root_only_percussive_hits():
    text = "C G\n"
    tune_src = chordsheet_to_tune(text, "tabla")
    result = analyze(parse(tune_src))
    events = result.note_events["tabla_pattern"]
    assert len(events) == 2  # one hit per chord entry, not a full chord
    assert all(ev.waveform == "noise" for ev in events)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))