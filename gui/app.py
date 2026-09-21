#!/usr/bin/env python3
"""
Tune DSL — web GUI backend.

A small Flask app that runs the REAL compiler pipeline (the same
lexer/parser/semantic/backends as tune.py) and serves a single-page
frontend for editing, compiling, and playing .tune programs in a
browser. No new compiler logic lives here -- this is purely a UI layer
over the existing src/ modules.

Run with:
    python3 gui/app.py
Then open http://127.0.0.1:5000 in a browser.
"""

import os
import sys
import tempfile
import traceback
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from flask import Flask, request, jsonify, send_from_directory, Response

from lexer import LexError
from parser import parse, ParseError
from semantic import analyze, SemanticError
import reference as ref
from audio_transcribe import transcribe_to_tune, TranscribeError
from audio_compare import compare_files, AudioCompareError
from audio_io import AudioReadError

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
EXAMPLES_DIR = os.path.join(APP_ROOT, "..", "examples")
OUTPUT_DIR = tempfile.mkdtemp(prefix="tunedsl_gui_")

app = Flask(__name__)


def compile_source(source: str, backend: str):
    """Runs the full pipeline; returns (result, error_message).
    error_message is None on success."""
    try:
        program = parse(source)
        result = analyze(program)
    except LexError as e:
        return None, f"Lex error: {e}"
    except ParseError as e:
        return None, f"Parse error: {e}"
    except SemanticError as e:
        return None, f"Error: {e}"
    return result, None


@app.route("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")


@app.route("/api/examples")
def list_examples():
    examples = {}
    if os.path.isdir(EXAMPLES_DIR):
        for fname in sorted(os.listdir(EXAMPLES_DIR)):
            if fname.endswith(".tune"):
                with open(os.path.join(EXAMPLES_DIR, fname)) as f:
                    examples[fname] = f.read()
    return jsonify(examples)


@app.route("/api/compile", methods=["POST"])
def api_compile():
    data = request.get_json(force=True)
    source = data.get("source", "")
    backend = data.get("backend", "python")

    result, error = compile_source(source, backend)
    if error:
        return jsonify({"ok": False, "error": error}), 400

    token = uuid.uuid4().hex
    wav_path = os.path.join(OUTPUT_DIR, f"{token}.wav")

    warning = None
    if not result.plays:
        warning = "No `play` statements found — output will be silent."

    try:
        if backend == "cpp":
            from codegen import generate_cpp
            import subprocess
            import shutil as shutil_mod
            if shutil_mod.which("g++") is None:
                return jsonify({"ok": False, "error": "g++ not found on server -- cpp backend unavailable"}), 400
            cpp_src = generate_cpp(result)
            with tempfile.TemporaryDirectory() as tmp:
                cpp_path = os.path.join(tmp, "song.cpp")
                exe_path = os.path.join(tmp, "song")
                with open(cpp_path, "w") as f:
                    f.write(cpp_src)
                r = subprocess.run(
                    ["g++", "-O3", "-march=native", "-ffast-math", "-flto", "-funroll-loops",
                     "-o", exe_path, cpp_path],
                    capture_output=True, text=True,
                )
                if r.returncode != 0:
                    return jsonify({"ok": False, "error": f"g++ failed:\n{r.stderr}"}), 400
                r = subprocess.run([exe_path, wav_path], capture_output=True, text=True)
                if r.returncode != 0:
                    return jsonify({"ok": False, "error": f"binary failed:\n{r.stderr}"}), 400
        elif backend == "mlir":
            from codegen_mlir import compile_and_run_mlir, MlirBackendError
            try:
                compile_and_run_mlir(result, wav_path)
            except MlirBackendError as e:
                return jsonify({"ok": False, "error": str(e)}), 400
        else:
            samples = ref.render_program(result)
            ref.write_wav(wav_path, samples)
    except Exception as e:
        return jsonify({"ok": False, "error": f"internal error: {e}\n{traceback.format_exc()}"}), 500

    duration = None
    try:
        import wave
        with wave.open(wav_path, "rb") as w:
            duration = w.getnframes() / w.getframerate()
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "audio_url": f"/api/audio/{token}.wav",
        "warning": warning,
        "tempo": result.tempo_bpm,
        "duration": duration,
        "dce_eliminated": result.dce_eliminated,
        "num_instruments": len(result.instruments),
        "num_plays": len(result.plays),
    })


@app.route("/api/audio/<path:filename>")
def api_audio(filename):
    return send_from_directory(OUTPUT_DIR, filename, mimetype="audio/wav")


@app.route("/api/export-midi", methods=["POST"])
def api_export_midi():
    data = request.get_json(force=True)
    source = data.get("source", "")

    result, error = compile_source(source, "python")
    if error:
        return jsonify({"ok": False, "error": error}), 400

    from midi_export import export_midi
    token = uuid.uuid4().hex
    midi_path = os.path.join(OUTPUT_DIR, f"{token}.mid")
    export_midi(result, midi_path)
    return jsonify({"ok": True, "midi_url": f"/api/midi/{token}.mid"})


@app.route("/api/midi/<path:filename>")
def api_midi(filename):
    return send_from_directory(OUTPUT_DIR, filename, mimetype="audio/midi", as_attachment=True,
                                download_name="tune_export.mid")


@app.route("/api/transcribe", methods=["POST"])
def api_transcribe():
    """Upload an audio file (a hummed/whistled/played reference melody)
    and get back a draft Tune DSL source -- see src/audio_transcribe.py
    for exactly what this is (monophonic, best-effort, meant to be tuned
    by hand afterward). Also stashes the uploaded file server-side under
    a token, so /api/compare below can reuse it without a second upload.
    """
    if "audio" not in request.files:
        return jsonify({"ok": False, "error": "no 'audio' file in the upload"}), 400
    upload = request.files["audio"]
    if upload.filename == "":
        return jsonify({"ok": False, "error": "empty filename"}), 400

    tempo = request.form.get("tempo")
    tempo_bpm = float(tempo) if tempo else None
    waveform = request.form.get("waveform", "sine")

    token = uuid.uuid4().hex
    ref_path = os.path.join(OUTPUT_DIR, f"{token}_reference.wav")
    upload.save(ref_path)

    try:
        source_text = transcribe_to_tune(ref_path, tempo_bpm=tempo_bpm, waveform=waveform)
    except (TranscribeError, AudioReadError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"internal error: {e}\n{traceback.format_exc()}"}), 500

    return jsonify({
        "ok": True,
        "source": source_text,
        "reference_token": token,
        "reference_audio_url": f"/api/audio/{token}_reference.wav",
    })


@app.route("/api/compare", methods=["POST"])
def api_compare():
    """Compare a previously-compiled 'actual' render against an 'expected'
    reference -- either a freshly uploaded file, or one already stashed
    server-side by a prior /api/transcribe call (reference_token). See
    src/audio_compare.py's module docstring for what the returned numbers
    mean (a correlation heuristic, not a perceptual judgment)."""
    actual_token = request.form.get("actual_token", "")
    if not actual_token:
        return jsonify({"ok": False, "error": "missing 'actual_token' -- compile something first"}), 400
    actual_path = os.path.join(OUTPUT_DIR, f"{actual_token}.wav")
    if not os.path.isfile(actual_path):
        return jsonify({"ok": False, "error": "that compiled audio has expired -- compile again"}), 400

    if "audio" in request.files and request.files["audio"].filename:
        token = uuid.uuid4().hex
        expected_path = os.path.join(OUTPUT_DIR, f"{token}_reference.wav")
        request.files["audio"].save(expected_path)
    else:
        reference_token = request.form.get("reference_token", "")
        expected_path = os.path.join(OUTPUT_DIR, f"{reference_token}_reference.wav")
        if not reference_token or not os.path.isfile(expected_path):
            return jsonify({"ok": False, "error": "no reference audio -- upload one, or transcribe one first"}), 400

    try:
        metrics = compare_files(expected_path, actual_path)
    except (AudioCompareError, AudioReadError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"internal error: {e}\n{traceback.format_exc()}"}), 500

    return jsonify({"ok": True, "metrics": metrics})


INDEX_HTML = None  # set below, loaded from index.html at import time
_html_path = os.path.join(APP_ROOT, "index.html")
if os.path.isfile(_html_path):
    with open(_html_path) as f:
        INDEX_HTML = f.read()


if __name__ == "__main__":
    print(f"Tune DSL GUI -- temp audio dir: {OUTPUT_DIR}")
    app.run(host="127.0.0.1", port=5000, debug=False)