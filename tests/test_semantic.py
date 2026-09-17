import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from parser import parse
from semantic import analyze, SemanticError
from pitch import pitch_to_freq


def approx(a, b, tol=0.01):
    return abs(a - b) < tol


def test_tempo_resolved():
    result = analyze(parse("tempo 140\ninstrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"))
    assert result.tempo_bpm == 140.0


def test_default_tempo_if_unspecified():
    result = analyze(parse("instrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"))
    assert result.tempo_bpm == 120.0


def test_instrument_registered():
    result = analyze(parse("instrument lead = square\npattern m { note C4 : 1/4 }\nplay lead m\n"))
    assert result.instruments == {"lead": "square"}


def test_invalid_waveform_raises():
    with pytest.raises(SemanticError):
        analyze(parse("instrument lead = triangleee\npattern m { note C4 : 1/4 }\nplay lead m\n"))


def test_play_undeclared_instrument_raises():
    with pytest.raises(SemanticError):
        analyze(parse("pattern m { note C4 : 1/4 }\nplay ghost m\n"))


def test_play_undeclared_pattern_raises():
    with pytest.raises(SemanticError):
        analyze(parse("instrument lead = sine\nplay lead ghost\n"))


def test_note_event_freq_and_duration():
    result = analyze(parse("instrument lead = sine\npattern m { note A4 : 1/4 }\nplay lead m\n"))
    events = result.note_events["m"]
    assert len(events) == 1
    ev = events[0]
    assert approx(ev.freq_hz, 440.0)
    assert approx(ev.duration_beats, 0.25)
    assert approx(ev.start_beat, 0.0)
    assert ev.waveform == "sine"


def test_note_sequence_start_beats_accumulate():
    src = "instrument lead = sine\npattern m {\n  note C4 : 1/4\n  note E4 : 1/4\n  note G4 : 1/2\n}\nplay lead m\n"
    result = analyze(parse(src))
    events = result.note_events["m"]
    assert len(events) == 3
    assert approx(events[0].start_beat, 0.0)
    assert approx(events[1].start_beat, 0.25)
    assert approx(events[2].start_beat, 0.5)
    assert approx(events[2].start_beat + events[2].duration_beats, 1.0)


def test_rest_advances_time_but_has_no_freq():
    src = "instrument lead = sine\npattern m {\n  note C4 : 1/4\n  rest : 1/4\n  note E4 : 1/4\n}\nplay lead m\n"
    result = analyze(parse(src))
    events = result.note_events["m"]
    assert events[1].freq_hz is None
    assert approx(events[1].start_beat, 0.25)
    assert approx(events[2].start_beat, 0.5)


def test_chord_events_share_start_beat():
    src = "instrument lead = sine\npattern m {\n  chord [C4, E4, G4] : 1/2\n}\nplay lead m\n"
    result = analyze(parse(src))
    events = result.note_events["m"]
    assert len(events) == 3
    for ev in events:
        assert approx(ev.start_beat, 0.0)
        assert approx(ev.duration_beats, 0.5)
    freqs = sorted(ev.freq_hz for ev in events)
    expected = sorted([pitch_to_freq("C4"), pitch_to_freq("E4"), pitch_to_freq("G4")])
    for a, b in zip(freqs, expected):
        assert approx(a, b)


def test_repeat_unrolls_correct_count_and_timing():
    src = "instrument lead = sine\npattern m {\n  repeat 3 {\n    note C4 : 1/4\n  }\n}\nplay lead m\n"
    result = analyze(parse(src))
    events = result.note_events["m"]
    assert len(events) == 3
    starts = [ev.start_beat for ev in events]
    assert approx(starts[0], 0.0)
    assert approx(starts[1], 0.25)
    assert approx(starts[2], 0.5)


def test_nested_repeat():
    src = (
        "instrument lead = sine\n"
        "pattern m {\n"
        "  repeat 2 {\n"
        "    repeat 2 {\n"
        "      note C4 : 1/4\n"
        "    }\n"
        "    rest : 1/4\n"
        "  }\n"
        "}\n"
        "play lead m\n"
    )
    result = analyze(parse(src))
    events = result.note_events["m"]
    # each outer iter: 2 notes + 1 rest = 3 events, x2 outer = 6
    assert len(events) == 6
    kinds = [ev.freq_hz is not None for ev in events]
    assert kinds == [True, True, False, True, True, False]


def test_let_variable_used_in_duration():
    src = (
        "let q = 1/4\n"
        "instrument lead = sine\n"
        "pattern m {\n  note C4 : q\n}\nplay lead m\n"
    )
    result = analyze(parse(src))
    ev = result.note_events["m"][0]
    assert approx(ev.duration_beats, 0.25)


def test_undefined_let_variable_raises():
    src = "instrument lead = sine\npattern m {\n  note C4 : q\n}\nplay lead m\n"
    with pytest.raises(SemanticError):
        analyze(parse(src))


def test_division_by_zero_duration_raises():
    src = "instrument lead = sine\npattern m {\n  note C4 : 1/0\n}\nplay lead m\n"
    with pytest.raises(SemanticError):
        analyze(parse(src))


def test_zero_duration_raises():
    src = "instrument lead = sine\npattern m {\n  note C4 : 0\n}\nplay lead m\n"
    with pytest.raises(SemanticError):
        analyze(parse(src))


def test_negative_repeat_count_raises():
    src = "instrument lead = sine\npattern m {\n  repeat -1 {\n    note C4 : 1/4\n  }\n}\nplay lead m\n"
    with pytest.raises(SemanticError):
        analyze(parse(src))


def test_redeclared_instrument_raises():
    src = "instrument lead = sine\ninstrument lead = square\npattern m { note C4 : 1/4 }\nplay lead m\n"
    with pytest.raises(SemanticError):
        analyze(parse(src))


def test_redeclared_pattern_raises():
    src = (
        "instrument lead = sine\n"
        "pattern m { note C4 : 1/4 }\n"
        "pattern m { note D4 : 1/4 }\n"
        "play lead m\n"
    )
    with pytest.raises(SemanticError):
        analyze(parse(src))


def test_multiple_plays_of_same_pattern_same_instrument():
    src = (
        "instrument lead = sine\n"
        "pattern m { note C4 : 1/4 }\n"
        "play lead m\n"
        "play lead m\n"
    )
    result = analyze(parse(src))
    assert result.plays == [("lead", "m"), ("lead", "m")]
    assert "m" in result.note_events


def test_note_velocity_default_is_one():
    src = "instrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    result = analyze(parse(src))
    assert result.note_events["m"][0].velocity == 1.0


def test_note_velocity_resolved():
    src = "instrument lead = sine\npattern m { note C4 : 1/4 @ 0.6 }\nplay lead m\n"
    result = analyze(parse(src))
    assert approx(result.note_events["m"][0].velocity, 0.6)


def test_chord_velocity_applies_to_all_notes():
    src = "instrument lead = sine\npattern m { chord [C4, E4] : 1/2 @ 0.3 }\nplay lead m\n"
    result = analyze(parse(src))
    for ev in result.note_events["m"]:
        assert approx(ev.velocity, 0.3)


def test_negative_velocity_raises():
    src = "instrument lead = sine\npattern m { note C4 : 1/4 @ -0.5 }\nplay lead m\n"
    with pytest.raises(SemanticError):
        analyze(parse(src))


def test_pulse_and_noise_are_valid_waveforms():
    src = "instrument a = pulse\ninstrument b = noise\npattern m { note C4 : 1/4 }\nplay a m\n"
    result = analyze(parse(src))
    assert result.instruments == {"a": "pulse", "b": "noise"}


def test_effect_lowpass_resolved():
    src = "effect lowpass 800\ninstrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    result = analyze(parse(src))
    assert result.effects == [("lowpass", [800.0])]


def test_effect_delay_resolved():
    src = "effect delay 0.25 0.4\ninstrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    result = analyze(parse(src))
    assert result.effects == [("delay", [0.25, 0.4])]


def test_effect_highpass_resolved():
    src = "effect highpass 200\ninstrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    result = analyze(parse(src))
    assert result.effects == [("highpass", [200.0])]


def test_effect_distortion_resolved():
    src = "effect distortion 3\ninstrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    result = analyze(parse(src))
    assert result.effects == [("distortion", [3.0])]


def test_effect_tremolo_resolved():
    src = "effect tremolo 5 0.6\ninstrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    result = analyze(parse(src))
    assert result.effects == [("tremolo", [5.0, 0.6])]


def test_unknown_effect_raises():
    src = "effect reverb 0.5\ninstrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    with pytest.raises(SemanticError):
        analyze(parse(src))


def test_effect_wrong_arity_raises():
    src = "effect lowpass 800 900\ninstrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    with pytest.raises(SemanticError):
        analyze(parse(src))


def test_no_effects_defaults_to_empty_list():
    src = "instrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    result = analyze(parse(src))
    assert result.effects == []


def test_full_program_end_to_end():
    src = (
        "tempo 100\n"
        "instrument lead = sine\n"
        "let q = 1/4\n"
        "pattern melody {\n"
        "  note C4 : q\n"
        "  note E4 : q\n"
        "  chord [C4, E4, G4] : 1/2\n"
        "  rest : 1/4\n"
        "  repeat 2 {\n"
        "    note G4 : 1/8\n"
        "  }\n"
        "}\n"
        "play lead melody\n"
    )
    result = analyze(parse(src))
    assert result.tempo_bpm == 100.0
    events = result.note_events["melody"]
    # 1 + 1 + 3 (chord) + 1 (rest) + 2 (repeat) = 8
    assert len(events) == 8
    assert approx(events[-1].start_beat + events[-1].duration_beats, 0.25+0.25+0.5+0.25+0.125+0.125)


def test_zero_velocity_note_is_dead_code_eliminated():
    # a velocity-0 note contributes nothing (multiplied by 0 everywhere
    # downstream), so it should be dropped from the event list entirely --
    # but timing must still advance correctly for the notes after it
    src = (
        "instrument lead = sine\n"
        "pattern m {\n"
        "  note C4 : 1/4 @ 0\n"
        "  note E4 : 1/4\n"
        "}\nplay lead m\n"
    )
    result = analyze(parse(src))
    events = result.note_events["m"]
    assert len(events) == 1  # only E4 survives
    assert events[0].freq_hz is not None
    assert approx(events[0].start_beat, 0.25)  # timing still advanced past the dead note
    assert result.dce_eliminated == 1


def test_zero_velocity_chord_note_is_dead_code_eliminated():
    src = (
        "instrument lead = sine\n"
        "pattern m { chord [C4, E4, G4] : 1/2 @ 0 }\nplay lead m\n"
    )
    result = analyze(parse(src))
    events = result.note_events["m"]
    assert len(events) == 0
    assert result.dce_eliminated == 3


def test_nonzero_velocity_not_eliminated():
    src = "instrument lead = sine\npattern m { note C4 : 1/4 @ 0.01 }\nplay lead m\n"
    result = analyze(parse(src))
    assert len(result.note_events["m"]) == 1
    assert result.dce_eliminated == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))