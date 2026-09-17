import subprocess
import sys
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")


def run_cli(*args):
    return subprocess.run(
        [sys.executable, os.path.join(ROOT, "tune.py"), *args],
        capture_output=True, text=True, cwd=ROOT,
    )


def test_cli_compiles_example_to_wav(tmp_path):
    out_path = tmp_path / "melody.wav"
    result = run_cli(os.path.join(ROOT, "examples", "melody.tune"), "-o", str(out_path))
    assert result.returncode == 0, result.stderr
    assert out_path.exists()
    assert out_path.stat().st_size > 44  # more than just a header
    assert "wrote" in result.stdout


def test_cli_missing_file_errors_cleanly():
    result = run_cli("does_not_exist.tune")
    assert result.returncode != 0
    assert "no such file" in result.stderr


def test_cli_syntax_error_reported():
    bad = os.path.join(ROOT, "tests", "_tmp_bad.tune")
    with open(bad, "w") as f:
        f.write("tempo 120 instrument lead = sine\n")
    try:
        result = run_cli(bad)
        assert result.returncode != 0
        assert "error" in result.stderr.lower()
    finally:
        os.remove(bad)


def test_cli_default_output_name(tmp_path):
    src = tmp_path / "song.tune"
    src.write_text("instrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n")
    result = run_cli(str(src))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "song.wav").exists()


def test_cli_cpp_backend(tmp_path):
    import shutil
    if shutil.which("g++") is None:
        import pytest
        pytest.skip("g++ not available")
    src = tmp_path / "song.tune"
    src.write_text("instrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n")
    out = tmp_path / "song.wav"
    result = run_cli(str(src), "-o", str(out), "--backend", "cpp")
    assert result.returncode == 0, result.stderr
    assert out.exists()
    assert out.stat().st_size > 44


def test_cli_mlir_backend(tmp_path):
    import shutil
    if any(shutil.which(t) is None for t in ("mlir-opt-19", "mlir-translate-19", "llc-19", "gcc")):
        import pytest
        pytest.skip("MLIR toolchain not available")
    src = tmp_path / "song.tune"
    src.write_text("instrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n")
    out = tmp_path / "song.wav"
    result = run_cli(str(src), "-o", str(out), "--backend", "mlir")
    assert result.returncode == 0, result.stderr
    assert out.exists()
    assert out.stat().st_size > 44


def test_cli_mlir_backend_handles_effects_and_alternate_waveforms(tmp_path):
    # regression test for the scope expansion: the MLIR backend now
    # supports everything the C++ backend does, not just the original
    # sine/square/saw/triangle-only subset
    import shutil
    if any(shutil.which(t) is None for t in ("mlir-opt-19", "mlir-translate-19", "llc-19", "gcc")):
        import pytest
        pytest.skip("MLIR toolchain not available")
    src = tmp_path / "song.tune"
    src.write_text(
        "effect lowpass 800\ninstrument perc = noise\npattern m { note C4 : 1/4 }\nplay perc m\n"
    )
    out = tmp_path / "song.wav"
    result = run_cli(str(src), "-o", str(out), "--backend", "mlir")
    assert result.returncode == 0, result.stderr
    assert out.exists()
    assert out.stat().st_size > 44


def test_cli_export_midi(tmp_path):
    src = tmp_path / "song.tune"
    src.write_text(
        "instrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    )
    wav_out = tmp_path / "song.wav"
    midi_out = tmp_path / "song.mid"
    result = run_cli(str(src), "-o", str(wav_out), "--export-midi", str(midi_out))
    assert result.returncode == 0, result.stderr
    assert wav_out.exists()
    assert midi_out.exists()
    assert midi_out.stat().st_size > 20  # more than just a bare header
    assert midi_out.read_bytes()[:4] == b"MThd"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))