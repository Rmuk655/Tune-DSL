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


INDEX_HTML = None  # set below, loaded from index.html at import time
_html_path = os.path.join(APP_ROOT, "index.html")
if os.path.isfile(_html_path):
    with open(_html_path) as f:
        INDEX_HTML = f.read()


if __name__ == "__main__":
    print(f"Tune DSL GUI -- temp audio dir: {OUTPUT_DIR}")
    app.run(host="127.0.0.1", port=5000, debug=False)