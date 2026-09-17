import subprocess
import sys
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")


def run_cli(*args):
    return subprocess.run(
        [sys.executable, os.path.join(ROOT, "chordsheet_cli.py"), *args],
        capture_output=True, text=True, cwd=ROOT,
    )


def write_sheet(path, text):
    with open(path, "w") as f:
        f.write(text)


def test_single_instrument_compiles_to_wav(tmp_path):
    sheet = tmp_path / "song.guitar"
    write_sheet(str(sheet), "tempo 100\nC G Am F\n")
    out = tmp_path / "song.wav"
    result = run_cli(str(sheet), "-o", str(out))
    assert result.returncode == 0, result.stderr
    assert out.exists()
    assert out.stat().st_size > 44


def test_to_tune_mode_prints_source_without_compiling(tmp_path):
    sheet = tmp_path / "song.guitar"
    write_sheet(str(sheet), "tempo 100\nC G\n")
    result = run_cli(str(sheet), "--to-tune")
    assert result.returncode == 0, result.stderr
    assert "instrument guitar" in result.stdout
    assert "chord [C3" in result.stdout
    assert not (tmp_path / "song.wav").exists()  # confirms it did NOT compile


def test_multiple_instruments_combine_into_one_file(tmp_path):
    guitar = tmp_path / "song.guitar"
    bass = tmp_path / "song.bass"
    write_sheet(str(guitar), "tempo 90\nC G Am F\n")
    write_sheet(str(bass), "C G Am F\n")
    out = tmp_path / "song.wav"
    result = run_cli(str(guitar), str(bass), "-o", str(out))
    assert result.returncode == 0, result.stderr
    assert "2 instrument(s)" in result.stdout
    assert out.exists()


def test_multiple_instruments_to_tune_shows_both_blocks(tmp_path):
    guitar = tmp_path / "song.guitar"
    keyboard = tmp_path / "song.keyboard"
    write_sheet(str(guitar), "tempo 100\nC\n")
    write_sheet(str(keyboard), "C\n")
    result = run_cli(str(guitar), str(keyboard), "--to-tune")
    assert result.returncode == 0
    assert "guitar_0" in result.stdout
    assert "keyboard_1" in result.stdout
    assert result.stdout.count("tempo") == 1  # combined into a single tempo line


def test_unrecognized_instrument_extension_errors_cleanly(tmp_path):
    sheet = tmp_path / "song.kazoo"
    write_sheet(str(sheet), "C G\n")
    result = run_cli(str(sheet), "--to-tune")
    assert result.returncode != 0
    assert "kazoo" in result.stderr
    assert "isn't a recognized instrument" in result.stderr


def test_invalid_chord_symbol_errors_cleanly(tmp_path):
    sheet = tmp_path / "song.guitar"
    write_sheet(str(sheet), "Hxyz G\n")
    result = run_cli(str(sheet), "--to-tune")
    assert result.returncode != 0


def test_missing_file_errors_cleanly():
    result = run_cli("does_not_exist.guitar")
    assert result.returncode != 0
    assert "no such file" in result.stderr


def test_conflicting_tempo_warns_but_still_compiles(tmp_path):
    guitar = tmp_path / "song.guitar"
    keyboard = tmp_path / "song.keyboard"
    write_sheet(str(guitar), "tempo 90\nC\n")
    write_sheet(str(keyboard), "tempo 140\nC\n")  # conflicting tempo
    out = tmp_path / "song.wav"
    result = run_cli(str(guitar), str(keyboard), "-o", str(out))
    assert result.returncode == 0
    assert "warning" in result.stderr.lower()
    assert out.exists()


def test_export_midi_alongside_wav(tmp_path):
    sheet = tmp_path / "song.guitar"
    write_sheet(str(sheet), "tempo 100\nC G\n")
    wav_out = tmp_path / "song.wav"
    midi_out = tmp_path / "song.mid"
    result = run_cli(str(sheet), "-o", str(wav_out), "--export-midi", str(midi_out))
    assert result.returncode == 0, result.stderr
    assert wav_out.exists()
    assert midi_out.exists()
    assert midi_out.read_bytes()[:4] == b"MThd"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))