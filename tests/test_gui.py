import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gui"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import json
import shutil
import wave
import io

import pytest

import app as gui_app


@pytest.fixture
def client():
    gui_app.app.config["TESTING"] = True
    with gui_app.app.test_client() as c:
        yield c


def test_index_page_loads(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Tune DSL Playground" in r.data
    assert b"CodeMirror" in r.data  # the editor library is actually referenced


def test_examples_endpoint_lists_bundled_tune_files(client):
    r = client.get("/api/examples")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "melody.tune" in data
    assert "tempo" in data["melody.tune"]  # actual file content, not a stub


def test_compile_python_backend_returns_valid_wav(client):
    src = "instrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    r = client.post("/api/compile", json={"source": src, "backend": "python"})
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["ok"] is True
    assert data["tempo"] == 120.0
    assert data["num_instruments"] == 1

    audio_resp = client.get(data["audio_url"])
    assert audio_resp.status_code == 200
    assert audio_resp.data[:4] == b"RIFF"
    # actually parse it as a WAV to confirm it's structurally valid
    with wave.open(io.BytesIO(audio_resp.data), "rb") as w:
        assert w.getnframes() > 0
        assert w.getframerate() == 44100


def test_compile_reports_lex_errors_cleanly(client):
    r = client.post("/api/compile", json={"source": "@@@ not valid @@@", "backend": "python"})
    assert r.status_code == 400
    data = json.loads(r.data)
    assert data["ok"] is False
    assert "error" in data


def test_compile_reports_parse_errors_cleanly(client):
    r = client.post("/api/compile", json={"source": "tempo 120 instrument x = sine\n", "backend": "python"})
    assert r.status_code == 400
    data = json.loads(r.data)
    assert data["ok"] is False


def test_compile_reports_semantic_errors_cleanly(client):
    src = "instrument lead = bogus_waveform\npattern m { note C4 : 1/4 }\nplay lead m\n"
    r = client.post("/api/compile", json={"source": src, "backend": "python"})
    assert r.status_code == 400
    data = json.loads(r.data)
    assert data["ok"] is False


def test_compile_warns_on_no_play_statements(client):
    src = "instrument lead = sine\npattern m { note C4 : 1/4 }\n"
    r = client.post("/api/compile", json={"source": src, "backend": "python"})
    data = json.loads(r.data)
    assert data["ok"] is True
    assert data["warning"] is not None
    assert "play" in data["warning"].lower()


def test_compile_reports_dce_stats(client):
    src = (
        "instrument lead = sine\n"
        "pattern m {\n  note C4 : 1/4 @ 0\n  note E4 : 1/4\n}\nplay lead m\n"
    )
    r = client.post("/api/compile", json={"source": src, "backend": "python"})
    data = json.loads(r.data)
    assert data["dce_eliminated"] == 1


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ not available")
def test_compile_cpp_backend_returns_valid_wav(client):
    src = "instrument lead = square\npattern m { note C4 : 1/4 }\nplay lead m\n"
    r = client.post("/api/compile", json={"source": src, "backend": "cpp"})
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["ok"] is True
    audio_resp = client.get(data["audio_url"])
    assert audio_resp.data[:4] == b"RIFF"


@pytest.mark.skipif(
    any(shutil.which(t) is None for t in ("mlir-opt-19", "mlir-translate-19", "llc-19", "gcc")),
    reason="MLIR toolchain not available",
)
def test_compile_mlir_backend_returns_valid_wav(client):
    src = "instrument lead = triangle\npattern m { note C4 : 1/4 }\nplay lead m\n"
    r = client.post("/api/compile", json={"source": src, "backend": "mlir"})
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["ok"] is True
    audio_resp = client.get(data["audio_url"])
    assert audio_resp.data[:4] == b"RIFF"


def test_export_midi_returns_valid_midi_file(client):
    src = "instrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    r = client.post("/api/export-midi", json={"source": src})
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["ok"] is True

    midi_resp = client.get(data["midi_url"])
    assert midi_resp.status_code == 200
    assert midi_resp.data[:4] == b"MThd"


def test_export_midi_reports_errors_cleanly(client):
    r = client.post("/api/export-midi", json={"source": "not valid !!!"})
    assert r.status_code == 400
    data = json.loads(r.data)
    assert data["ok"] is False


def test_unknown_backend_falls_back_gracefully(client):
    # an unrecognized backend string should behave like the default
    # (python) rather than crashing the server
    src = "instrument lead = sine\npattern m { note C4 : 1/4 }\nplay lead m\n"
    r = client.post("/api/compile", json={"source": src, "backend": "nonsense"})
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["ok"] is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))