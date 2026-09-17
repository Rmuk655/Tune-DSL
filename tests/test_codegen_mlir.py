import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import shutil
import subprocess
import wave

import numpy as np
import pytest

from parser import parse
from semantic import analyze
import reference as ref
from codegen_mlir import generate_mlir, compile_and_run_mlir, MlirBackendError

MLIR_TOOLS = ("mlir-opt-19", "mlir-translate-19", "llc-19", "gcc")
requires_mlir = pytest.mark.skipif(
    any(shutil.which(t) is None for t in MLIR_TOOLS),
    reason="mlir-opt-19/mlir-translate-19/llc-19/gcc not all available on this machine",
)


def read_wav_pcm(path):
    with wave.open(path, "rb") as w:
        n = w.getnframes()
        raw = w.readframes(n)
        return np.frombuffer(raw, dtype=np.int16)


def diff_max(path_a, path_b):
    a = read_wav_pcm(path_a)
    b = read_wav_pcm(path_b)
    assert len(a) == len(b), f"length mismatch: {len(a)} vs {len(b)}"
    return int(np.abs(a.astype(np.int32) - b.astype(np.int32)).max())


# -- generate_mlir unit tests (no external tools needed) --

def test_generate_mlir_produces_generic_function_library():
    src = "instrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    result = analyze(parse(src))
    mlir_text, total_samples, delay_effects = generate_mlir(result)
    # the fixed, generic function library must always be present
    assert "func.func @synth_event" in mlir_text
    assert "func.func @apply_lowpass" in mlir_text
    assert "func.func @apply_highpass" in mlir_text
    assert "func.func @apply_distortion" in mlir_text
    assert "func.func @apply_tremolo" in mlir_text
    assert "func.func @apply_delay" in mlir_text
    assert "scf.index_switch" in mlir_text  # runtime waveform dispatch
    assert "func.call @synth_event" in mlir_text
    assert total_samples > 0
    assert delay_effects == []


def test_generate_mlir_no_duplicate_waveform_math_per_event():
    # the whole point of the generic design: N notes should NOT produce
    # N copies of the sine-computation code -- there's exactly one
    # @synth_event definition regardless of how many notes call it
    src = (
        "instrument lead = sine\n"
        "pattern m {\n  note C4:1/8\n note D4:1/8\n note E4:1/8\n note F4:1/8\n"
        "  note G4:1/8\n note A4:1/8\n note B4:1/8\n note C5:1/8\n}\nplay lead m\n"
    )
    result = analyze(parse(src))
    mlir_text, _, _ = generate_mlir(result)
    assert mlir_text.count("func.func @synth_event") == 1
    assert mlir_text.count("func.call @synth_event") == 8  # one call per note


def test_generate_mlir_supports_all_six_waveforms():
    for wf in ["sine", "square", "saw", "triangle", "pulse", "noise"]:
        src = f"instrument x = {wf}\npattern m {{ note C4 : 1/4 }}\nplay x m\n"
        result = analyze(parse(src))
        mlir_text, _, _ = generate_mlir(result)  # must not raise
        assert "func.call @synth_event" in mlir_text


def test_generate_mlir_supports_all_five_effects():
    src = (
        "effect lowpass 800\neffect highpass 200\neffect distortion 3\n"
        "effect tremolo 5 0.5\neffect delay 0.2 0.3\n"
        "instrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    )
    result = analyze(parse(src))
    mlir_text, _, delay_effects = generate_mlir(result)
    assert "func.call @apply_lowpass" in mlir_text
    assert "func.call @apply_highpass" in mlir_text
    assert "func.call @apply_distortion" in mlir_text
    assert "func.call @apply_tremolo" in mlir_text
    assert delay_effects == [[0.2, 0.3]] or delay_effects == [(0.2, 0.3)]


def test_generate_mlir_rests_produce_no_synth_call_for_that_event():
    src = "instrument lead = sine\npattern m { rest : 1/4 }\nplay lead m\n"
    result = analyze(parse(src))
    mlir_text, _, _ = generate_mlir(result)
    assert "func.call @synth_event" not in mlir_text


def test_generate_mlir_no_events_still_valid():
    src = "instrument lead = sine\npattern m { note C4 : 1/4 }\n"  # no play
    result = analyze(parse(src))
    mlir_text, total_samples, _ = generate_mlir(result)
    assert "func.func @synth_event" in mlir_text
    assert total_samples == 1


# -- full pipeline tests (need mlir-opt/mlir-translate/llc/gcc) --

@requires_mlir
def test_mlir_output_is_valid_and_compiles(tmp_path):
    src = "instrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    result = analyze(parse(src))
    mlir_text, _, _ = generate_mlir(result)
    mlir_path = tmp_path / "test.mlir"
    mlir_path.write_text(mlir_text)
    proc = subprocess.run(["mlir-opt-19", str(mlir_path)], capture_output=True, text=True)
    assert proc.returncode == 0, f"mlir-opt rejected generated MLIR:\n{proc.stderr}"


@requires_mlir
@pytest.mark.parametrize("waveform", ["sine", "square", "saw", "triangle", "pulse", "noise"])
def test_each_waveform_matches_python_reference(tmp_path, waveform):
    src = f"instrument x = {waveform}\npattern m {{ note C4 : 2 }}\nplay x m\n"
    result = analyze(parse(src))
    py_path = str(tmp_path / "py.wav")
    mlir_path = str(tmp_path / "mlir.wav")
    ref.write_wav(py_path, ref.render_program(result))
    compile_and_run_mlir(result, mlir_path)
    assert diff_max(py_path, mlir_path) <= 3


@requires_mlir
def test_velocity_matches_python_reference(tmp_path):
    src = (
        "instrument lead = sine\n"
        "pattern m {\n  note C4 : 1/4 @ 0.5\n  note E4 : 1/4 @ 0.9\n}\nplay lead m\n"
    )
    result = analyze(parse(src))
    py_path = str(tmp_path / "py.wav")
    mlir_path = str(tmp_path / "mlir.wav")
    ref.write_wav(py_path, ref.render_program(result))
    compile_and_run_mlir(result, mlir_path)
    assert diff_max(py_path, mlir_path) <= 3


@requires_mlir
@pytest.mark.parametrize("effect_line,pattern_src", [
    ("effect lowpass 800", "instrument lead = square\npattern m { note C4 : 2 }\nplay lead m\n"),
    ("effect highpass 300", "instrument lead = square\npattern m { note C4 : 1 }\nplay lead m\n"),
    ("effect distortion 4", "instrument lead = sine\npattern m { note C4 : 1 }\nplay lead m\n"),
    ("effect tremolo 6 0.8", "instrument lead = sine\npattern m { note C4 : 1 }\nplay lead m\n"),
    ("effect delay 0.15 0.4", "instrument lead = sine\npattern m { note C4 : 1 }\nplay lead m\n"),
])
def test_each_effect_matches_python_reference(tmp_path, effect_line, pattern_src):
    src = effect_line + "\n" + pattern_src
    result = analyze(parse(src))
    py_path = str(tmp_path / "py.wav")
    mlir_path = str(tmp_path / "mlir.wav")
    ref.write_wav(py_path, ref.render_program(result))
    compile_and_run_mlir(result, mlir_path)
    assert diff_max(py_path, mlir_path) <= 3


@requires_mlir
def test_full_stress_song_matches_python_reference(tmp_path):
    # every waveform, velocity, all 5 effects chained, multiple layered
    # instruments, chords, rests, repeat -- the maximal coverage test
    src = """
tempo 100
effect lowpass 1200
effect highpass 100
effect distortion 2
effect tremolo 5 0.3
effect delay 0.2 0.35
instrument lead = sine
instrument bass = square
instrument perc = noise
instrument pad = pulse
instrument mid = saw
instrument hi = triangle
pattern melody {
  note C4 : 1/4 @ 0.8
  note E4 : 1/4 @ 0.6
  chord [C4, E4, G4] : 1/2 @ 0.9
  repeat 2 {
    note G4 : 1/8 @ 0.4
  }
}
pattern bassline {
  note C3 : 1/2 @ 1.0
  note G2 : 1/2 @ 0.7
}
pattern hits {
  note C4 : 1/8 @ 0.3
  rest : 1/8
  note C4 : 1/8 @ 0.3
  rest : 1/8
}
pattern padline {
  chord [C3, G3] : 2 @ 0.25
}
pattern midline {
  note E3 : 1 @ 0.5
}
pattern hiline {
  note A4 : 1 @ 0.4
}
play lead melody
play bass bassline
play perc hits
play pad padline
play mid midline
play hi hiline
"""
    result = analyze(parse(src))
    py_path = str(tmp_path / "py.wav")
    mlir_path = str(tmp_path / "mlir.wav")
    ref.write_wav(py_path, ref.render_program(result))
    compile_and_run_mlir(result, mlir_path)
    assert diff_max(py_path, mlir_path) <= 5


@requires_mlir
def test_rest_only_produces_silence(tmp_path):
    src = "instrument lead = sine\npattern m { rest : 1 }\nplay lead m\n"
    result = analyze(parse(src))
    out_path = str(tmp_path / "out.wav")
    compile_and_run_mlir(result, out_path)
    pcm = read_wav_pcm(out_path)
    assert np.max(np.abs(pcm)) == 0


@requires_mlir
def test_compile_and_run_reports_missing_tool_cleanly(tmp_path, monkeypatch):
    src = "instrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    result = analyze(parse(src))
    original_which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "llc-19" else original_which(name))
    with pytest.raises(MlirBackendError, match="llc-19"):
        compile_and_run_mlir(result, str(tmp_path / "out.wav"))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))