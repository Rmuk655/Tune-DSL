"""
Tune DSL — MLIR code generator (v2: genuine generic codegen).

Uses STANDARD MLIR dialects only (func, arith, scf, memref, math, index)
-- there is no custom "Tune dialect". Building a real one means writing
TableGen op definitions and a C++ dialect/conversion-pass library, which
is a multi-day engineering effort on its own, not something to fake.

DESIGN (this is the part that changed from v1): rather than unrolling one
specialized, constant-baked loop per note event, this generates a SMALL,
FIXED set of generic, parameterized functions -- @synth_event (waveform
chosen by a RUNTIME switch, scf.index_switch, not a compile-time
specialization) and one function per effect (@apply_lowpass,
@apply_highpass, @apply_distortion, @apply_tremolo, @apply_delay). Each
note event becomes a call to @synth_event with its data (freq,
start_sample, n_samples, waveform_id, velocity) as arguments, not a
freshly-generated block of inlined arithmetic. This mirrors how the C++
backend calls its templated synth_event<W>() once per event, except here
the waveform dispatch itself is a genuine runtime switch inside the IR,
not a compile-time template instantiation -- so it's MORE general than
the C++ version, not less.

SCOPE: covers everything the C++ backend covers -- sine, square, saw,
triangle, pulse, noise, velocity, and all 5 effects (lowpass, highpass,
distortion, tremolo, delay).

Pipeline (all real, shell out and verify yourself):
    mlir-opt-19        (lowers scf/arith/math/memref/func -> llvm dialect)
    mlir-translate-19  (llvm dialect MLIR -> LLVM IR text)
    llc-19             (LLVM IR -> native object file)
    gcc                (links the object file with a small C driver + WAV writer)
"""

import math
import subprocess
import tempfile
import os
import shutil

from semantic import SemanticResult

SAMPLE_RATE = 44100
WAVEFORM_ID = {"sine": 0, "square": 1, "saw": 2, "triangle": 3, "pulse": 4, "noise": 5}
EFFECT_ID = {"lowpass": 0, "highpass": 1, "distortion": 2, "tremolo": 3, "delay": 4}


class MlirBackendError(Exception):
    pass


def _beats_to_seconds(beats: float, tempo_bpm: float) -> float:
    return beats * (60.0 / tempo_bpm)


# The fixed, generic function library -- written once, called many times.
# Verified independently (see mlir_test/synth_event_prototype.mlir and
# mlir_test/effects_prototype.mlir) before being embedded here: each was
# compiled through the full mlir-opt -> mlir-translate -> llc pipeline and
# numerically diffed against reference.py, waveform by waveform and
# effect by effect, prior to this integration.
_MLIR_FUNCTION_LIBRARY = r"""
func.func @synth_event(%buffer: memref<?xf64>, %total_samples: index,
                        %freq: f64, %start_sample: index, %n_samples: index,
                        %waveform_id: index, %velocity: f64) {
  %c0 = arith.constant 0 : index
  %c1 = arith.constant 1 : index
  %remaining = arith.subi %total_samples, %start_sample : index
  %hi_cmp = arith.cmpi slt, %n_samples, %remaining : index
  %hi = arith.select %hi_cmp, %n_samples, %remaining : index
  %sample_rate = arith.constant 44100.0 : f64
  %fade_const = arith.constant 220 : index
  %two_idx = arith.constant 2 : index
  %n_half2 = arith.divsi %n_samples, %two_idx : index
  %fade_cmp = arith.cmpi slt, %fade_const, %n_half2 : index
  %fade_samples = arith.select %fade_cmp, %fade_const, %n_half2 : index
  %hi_gt_lo = arith.cmpi sgt, %hi, %c0 : index
  scf.if %hi_gt_lo {
    scf.for %s = %c0 to %hi step %c1 {
      %s_i64 = arith.index_cast %s : index to i64
      %s_f = arith.sitofp %s_i64 : i64 to f64
      %t = arith.divf %s_f, %sample_rate : f64
      %raw = arith.mulf %freq, %t : f64
      %raw_floor = math.floor %raw : f64
      %phase = arith.subf %raw, %raw_floor : f64
      %abs_idx = arith.addi %s, %start_sample : index
      %abs_idx_i64 = arith.index_cast %abs_idx : index to i64
      %abs_idx_i32 = arith.trunci %abs_idx_i64 : i64 to i32
      %wave = scf.index_switch %waveform_id -> f64
      case 0 {
        %two_pi = arith.constant 6.283185307179586 : f64
        %angle = arith.mulf %phase, %two_pi : f64
        %v = math.sin %angle : f64
        scf.yield %v : f64
      }
      case 1 {
        %two = arith.constant 2.0 : f64
        %scaled = arith.mulf %phase, %two : f64
        %floored = math.floor %scaled : f64
        %term = arith.mulf %floored, %two : f64
        %one = arith.constant 1.0 : f64
        %v = arith.subf %one, %term : f64
        scf.yield %v : f64
      }
      case 2 {
        %two = arith.constant 2.0 : f64
        %scaled = arith.mulf %phase, %two : f64
        %one = arith.constant 1.0 : f64
        %v = arith.subf %scaled, %one : f64
        scf.yield %v : f64
      }
      case 3 {
        %two = arith.constant 2.0 : f64
        %scaled = arith.mulf %phase, %two : f64
        %one = arith.constant 1.0 : f64
        %centered = arith.subf %scaled, %one : f64
        %absv = math.absf %centered : f64
        %doubled = arith.mulf %absv, %two : f64
        %one2 = arith.constant 1.0 : f64
        %v = arith.subf %doubled, %one2 : f64
        scf.yield %v : f64
      }
      case 4 {
        %four = arith.constant 4.0 : f64
        %scaled = arith.mulf %phase, %four : f64
        %floored = math.floor %scaled : f64
        %one_f = arith.constant 1.0 : f64
        %capped = arith.minimumf %floored, %one_f : f64
        %two = arith.constant 2.0 : f64
        %term = arith.mulf %capped, %two : f64
        %v = arith.subf %one_f, %term : f64
        scf.yield %v : f64
      }
      case 5 {
        %c16 = arith.constant 16 : i32
        %c15 = arith.constant 15 : i32
        %m1 = arith.constant 2146121005 : i32
        %m2 = arith.constant -2073254261 : i32
        %s1 = arith.shrui %abs_idx_i32, %c16 : i32
        %x1 = arith.xori %abs_idx_i32, %s1 : i32
        %x2 = arith.muli %x1, %m1 : i32
        %s2 = arith.shrui %x2, %c15 : i32
        %x3 = arith.xori %x2, %s2 : i32
        %x4 = arith.muli %x3, %m2 : i32
        %s3 = arith.shrui %x4, %c16 : i32
        %x5 = arith.xori %x4, %s3 : i32
        %h_f = arith.uitofp %x5 : i32 to f64
        %denom = arith.constant 4294967295.0 : f64
        %ratio = arith.divf %h_f, %denom : f64
        %two = arith.constant 2.0 : f64
        %scaled = arith.mulf %ratio, %two : f64
        %one = arith.constant 1.0 : f64
        %v = arith.subf %scaled, %one : f64
        scf.yield %v : f64
      }
      default {
        %zero = arith.constant 0.0 : f64
        scf.yield %zero : f64
      }
      %fade_gt_1 = arith.cmpi sgt, %fade_samples, %c1 : index
      %env = scf.if %fade_gt_1 -> f64 {
        %fade_m1 = arith.subi %fade_samples, %c1 : index
        %fade_m1_i64 = arith.index_cast %fade_m1 : index to i64
        %fade_m1_f = arith.sitofp %fade_m1_i64 : i64 to f64
        %one_f = arith.constant 1.0 : f64
        %inv_fade = arith.divf %one_f, %fade_m1_f : f64
        %attack = arith.mulf %s_f, %inv_fade : f64
        %n_i64 = arith.index_cast %n_samples : index to i64
        %n_f = arith.sitofp %n_i64 : i64 to f64
        %n_m1_f = arith.subf %n_f, %one_f : f64
        %release_base = arith.subf %n_m1_f, %s_f : f64
        %release = arith.mulf %release_base, %inv_fade : f64
        %min1 = arith.minimumf %attack, %release : f64
        %min2 = arith.minimumf %min1, %one_f : f64
        %zero_f = arith.constant 0.0 : f64
        %clamped = arith.maximumf %min2, %zero_f : f64
        scf.yield %clamped : f64
      } else {
        %one_f = arith.constant 1.0 : f64
        scf.yield %one_f : f64
      }
      %contrib1 = arith.mulf %wave, %env : f64
      %contrib2 = arith.mulf %contrib1, %velocity : f64
      %old = memref.load %buffer[%abs_idx] : memref<?xf64>
      %new = arith.addf %old, %contrib2 : f64
      memref.store %new, %buffer[%abs_idx] : memref<?xf64>
    }
  }
  return
}

func.func @apply_lowpass(%buffer: memref<?xf64>, %n: index, %cutoff_hz: f64) {
  %c0 = arith.constant 0 : index
  %c1 = arith.constant 1 : index
  %zero = arith.constant 0.0 : f64
  %cutoff_gt_0 = arith.cmpf ogt, %cutoff_hz, %zero : f64
  scf.if %cutoff_gt_0 {
    %dt = arith.constant 0.0000226757 : f64
    %one = arith.constant 1.0 : f64
    %two_pi = arith.constant 6.283185307179586 : f64
    %rc_denom = arith.mulf %two_pi, %cutoff_hz : f64
    %rc = arith.divf %one, %rc_denom : f64
    %alpha_denom = arith.addf %rc, %dt : f64
    %alpha = arith.divf %dt, %alpha_denom : f64
    %final = scf.for %i = %c0 to %n step %c1 iter_args(%prev = %zero) -> f64 {
      %x = memref.load %buffer[%i] : memref<?xf64>
      %diff = arith.subf %x, %prev : f64
      %delta = arith.mulf %alpha, %diff : f64
      %new = arith.addf %prev, %delta : f64
      memref.store %new, %buffer[%i] : memref<?xf64>
      scf.yield %new : f64
    }
  }
  return
}

func.func @apply_highpass(%buffer: memref<?xf64>, %n: index, %cutoff_hz: f64) {
  %c0 = arith.constant 0 : index
  %c1 = arith.constant 1 : index
  %zero = arith.constant 0.0 : f64
  %cutoff_gt_0 = arith.cmpf ogt, %cutoff_hz, %zero : f64
  scf.if %cutoff_gt_0 {
    %dt = arith.constant 0.0000226757 : f64
    %one = arith.constant 1.0 : f64
    %two_pi = arith.constant 6.283185307179586 : f64
    %rc_denom = arith.mulf %two_pi, %cutoff_hz : f64
    %rc = arith.divf %one, %rc_denom : f64
    %alpha_denom = arith.addf %rc, %dt : f64
    %alpha = arith.divf %rc, %alpha_denom : f64
    %x0 = memref.load %buffer[%c0] : memref<?xf64>
    %r:2 = scf.for %i = %c0 to %n step %c1 iter_args(%prev_y = %zero, %prev_x = %x0) -> (f64, f64) {
      %x = memref.load %buffer[%i] : memref<?xf64>
      %sum1 = arith.addf %prev_y, %x : f64
      %sum2 = arith.subf %sum1, %prev_x : f64
      %new_y = arith.mulf %alpha, %sum2 : f64
      memref.store %new_y, %buffer[%i] : memref<?xf64>
      scf.yield %new_y, %x : f64, f64
    }
  }
  return
}

func.func @apply_distortion(%buffer: memref<?xf64>, %n: index, %drive: f64) {
  %c0 = arith.constant 0 : index
  %c1 = arith.constant 1 : index
  %zero = arith.constant 0.0 : f64
  %drive_gt_0 = arith.cmpf ogt, %drive, %zero : f64
  scf.if %drive_gt_0 {
    %norm = math.tanh %drive : f64
    %eps = arith.constant 0.000000001 : f64
    %norm_ok = arith.cmpf oge, %norm, %eps : f64
    scf.if %norm_ok {
      scf.for %i = %c0 to %n step %c1 {
        %x = memref.load %buffer[%i] : memref<?xf64>
        %scaled = arith.mulf %drive, %x : f64
        %t = math.tanh %scaled : f64
        %v = arith.divf %t, %norm : f64
        memref.store %v, %buffer[%i] : memref<?xf64>
      }
    }
  }
  return
}

func.func @apply_tremolo(%buffer: memref<?xf64>, %n: index, %rate_hz: f64, %depth_in: f64) {
  %c0 = arith.constant 0 : index
  %c1 = arith.constant 1 : index
  %zero = arith.constant 0.0 : f64
  %rate_ok = arith.cmpf ogt, %rate_hz, %zero : f64
  %depth_ok = arith.cmpf ogt, %depth_in, %zero : f64
  %both_ok = arith.andi %rate_ok, %depth_ok : i1
  scf.if %both_ok {
    %one = arith.constant 1.0 : f64
    %depth_cap = arith.minimumf %depth_in, %one : f64
    %sample_rate = arith.constant 44100.0 : f64
    %two_pi = arith.constant 6.283185307179586 : f64
    %half = arith.constant 0.5 : f64
    scf.for %i = %c0 to %n step %c1 {
      %i_i64 = arith.index_cast %i : index to i64
      %i_f = arith.sitofp %i_i64 : i64 to f64
      %t = arith.divf %i_f, %sample_rate : f64
      %angle = arith.mulf %t, %rate_hz : f64
      %angle2 = arith.mulf %angle, %two_pi : f64
      %s = math.sin %angle2 : f64
      %s_half = arith.mulf %s, %half : f64
      %lfo = arith.addf %half, %s_half : f64
      %atten = arith.mulf %depth_cap, %lfo : f64
      %gain = arith.subf %one, %atten : f64
      %x = memref.load %buffer[%i] : memref<?xf64>
      %v = arith.mulf %x, %gain : f64
      memref.store %v, %buffer[%i] : memref<?xf64>
    }
  }
  return
}

func.func @apply_delay(%in_buf: memref<?xf64>, %out_buf: memref<?xf64>,
                        %in_n: index, %out_n: index,
                        %delay_samples: index, %feedback: f64) {
  %c0 = arith.constant 0 : index
  %c1 = arith.constant 1 : index
  %zero = arith.constant 0.0 : f64
  scf.for %i = %c0 to %out_n step %c1 {
    %in_bounds = arith.cmpi slt, %i, %in_n : index
    %x = scf.if %in_bounds -> f64 {
      %v = memref.load %in_buf[%i] : memref<?xf64>
      scf.yield %v : f64
    } else {
      scf.yield %zero : f64
    }
    %has_delay = arith.cmpi sge, %i, %delay_samples : index
    %fb = scf.if %has_delay -> f64 {
      %lag_idx = arith.subi %i, %delay_samples : index
      %prev_out = memref.load %out_buf[%lag_idx] : memref<?xf64>
      %scaled = arith.mulf %prev_out, %feedback : f64
      scf.yield %scaled : f64
    } else {
      scf.yield %zero : f64
    }
    %y = arith.addf %x, %fb : f64
    memref.store %y, %out_buf[%i] : memref<?xf64>
  }
  return
}
"""


def generate_mlir(result: SemanticResult, sample_rate: int = SAMPLE_RATE):
    """Generates the MLIR module: the fixed function library above, plus a
    @run_program function that CALLS those generic functions once per
    note event / effect with per-event data as arguments (not inlined,
    freshly-generated arithmetic per event)."""
    all_events = []
    for _instrument, pattern in result.plays:
        all_events.extend(result.note_events[pattern])

    # `slide` (frequency glide) and per-instrument `envelope` overrides
    # are implemented in reference.py (the Python backend) but not yet
    # ported here -- fail clearly rather than silently produce audio
    # that doesn't match what the Python backend would render.
    for ev in all_events:
        if getattr(ev, "slide_from_freq", None) is not None:
            raise MlirBackendError(
                "the MLIR backend does not yet support `slide` (frequency glide) -- "
                "use --backend python for programs that use slide"
            )
        if getattr(ev, "attack_sec", None) is not None or getattr(ev, "release_sec", None) is not None:
            raise MlirBackendError(
                "the MLIR backend does not yet support per-instrument `envelope` "
                "overrides -- use --backend python for programs that use envelope"
            )

    if all_events:
        total_beats = max(ev.start_beat + ev.duration_beats for ev in all_events)
        total_sec = _beats_to_seconds(total_beats, result.tempo_bpm)
        total_samples = int(math.ceil(total_sec * sample_rate)) + 1
    else:
        total_samples = 1

    call_lines = []
    for ev in all_events:
        if ev.freq_hz is None:
            continue
        start_sec = _beats_to_seconds(ev.start_beat, result.tempo_bpm)
        dur_sec = _beats_to_seconds(ev.duration_beats, result.tempo_bpm)
        start_sample = int(round(start_sec * sample_rate))
        n_samples = int(round(dur_sec * sample_rate))
        if n_samples <= 0:
            continue
        wid = WAVEFORM_ID[ev.waveform]
        vel = getattr(ev, "velocity", 1.0)
        i = len(call_lines)
        call_lines.append(
            f"  %c_start{i} = arith.constant {start_sample} : index\n"
            f"  %c_n{i} = arith.constant {n_samples} : index\n"
            f"  %c_wf{i} = arith.constant {wid} : index\n"
            f"  %c_freq{i} = arith.constant {float(ev.freq_hz)!r} : f64\n"
            f"  %c_vel{i} = arith.constant {float(vel)!r} : f64\n"
            f"  func.call @synth_event(%buf, %total, %c_freq{i}, "
            f"%c_start{i}, %c_n{i}, %c_wf{i}, %c_vel{i}) "
            f": (memref<?xf64>, index, f64, index, index, index, f64) -> ()\n"
        )
    synth_calls = "".join(call_lines) if call_lines else "  // (no pitched events)\n"

    # delay needs a resized buffer (a host-side/C concern, same as the
    # C++ backend's std::vector resize), so it's handled by the C driver,
    # not called from @run_program. Everything else modifies in place.
    inplace_effect_lines = []
    delay_effects = []
    for name, args in (result.effects or []):
        if name == "delay":
            delay_effects.append(args)
            continue
        eid = len(inplace_effect_lines)
        if name == "lowpass":
            inplace_effect_lines.append(
                f"  %ec{eid} = arith.constant {float(args[0])!r} : f64\n"
                f"  func.call @apply_lowpass(%buf, %total, %ec{eid}) : (memref<?xf64>, index, f64) -> ()\n"
            )
        elif name == "highpass":
            inplace_effect_lines.append(
                f"  %ec{eid} = arith.constant {float(args[0])!r} : f64\n"
                f"  func.call @apply_highpass(%buf, %total, %ec{eid}) : (memref<?xf64>, index, f64) -> ()\n"
            )
        elif name == "distortion":
            inplace_effect_lines.append(
                f"  %ec{eid} = arith.constant {float(args[0])!r} : f64\n"
                f"  func.call @apply_distortion(%buf, %total, %ec{eid}) : (memref<?xf64>, index, f64) -> ()\n"
            )
        elif name == "tremolo":
            inplace_effect_lines.append(
                f"  %ec{eid}a = arith.constant {float(args[0])!r} : f64\n"
                f"  %ec{eid}b = arith.constant {float(args[1])!r} : f64\n"
                f"  func.call @apply_tremolo(%buf, %total, %ec{eid}a, %ec{eid}b) "
                f": (memref<?xf64>, index, f64, f64) -> ()\n"
            )
    effect_calls = "".join(inplace_effect_lines)

    mlir_text = f"""// Auto-generated by Tune DSL codegen_mlir.py -- standard MLIR dialects
// only (func, arith, scf, memref, math, index). No custom Tune dialect.
// See codegen_mlir.py for the design rationale (generic functions called
// per event, runtime waveform dispatch, not per-event unrolled code).
{_MLIR_FUNCTION_LIBRARY}
func.func @run_program(%buf: memref<?xf64>, %total: index) {{
{synth_calls}{effect_calls}  return
}}
"""
    return mlir_text, total_samples, delay_effects


def compile_and_run_mlir(result: SemanticResult, out_wav_path: str, sample_rate: int = SAMPLE_RATE):
    """Runs the real pipeline end to end. Requires mlir-opt-19,
    mlir-translate-19, llc-19, and gcc on PATH."""
    for tool in ("mlir-opt-19", "mlir-translate-19", "llc-19", "gcc"):
        if shutil.which(tool) is None:
            raise MlirBackendError(f"required tool {tool!r} not found on PATH")

    mlir_text, total_samples, delay_effects = generate_mlir(result, sample_rate)

    with tempfile.TemporaryDirectory() as tmp:
        mlir_path = os.path.join(tmp, "synth.mlir")
        lowered_path = os.path.join(tmp, "lowered.mlir")
        ll_path = os.path.join(tmp, "synth.ll")
        obj_path = os.path.join(tmp, "synth.o")
        driver_path = os.path.join(tmp, "driver.c")
        exe_path = os.path.join(tmp, "synth")

        with open(mlir_path, "w") as f:
            f.write(mlir_text)

        r = subprocess.run(
            ["mlir-opt-19", mlir_path,
             "--canonicalize", "--cse",
             "--convert-scf-to-cf", "--convert-math-to-libm",
             "--convert-math-to-llvm", "--convert-arith-to-llvm",
             "--finalize-memref-to-llvm", "--convert-func-to-llvm",
             "--convert-cf-to-llvm", "--convert-index-to-llvm",
             "--reconcile-unrealized-casts", "--canonicalize", "--cse",
             "-o", lowered_path],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise MlirBackendError(f"mlir-opt failed:\n{r.stderr}\n\nGenerated MLIR was:\n{mlir_text}")

        r = subprocess.run(
            ["mlir-translate-19", "--mlir-to-llvmir", lowered_path, "-o", ll_path],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise MlirBackendError(f"mlir-translate failed:\n{r.stderr}")

        r = subprocess.run(
            ["llc-19", "-O3", "-filetype=obj", ll_path, "-o", obj_path],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise MlirBackendError(f"llc failed:\n{r.stderr}")

        delay_code = ""
        if delay_effects:
            steps = []
            for delay_sec, feedback in delay_effects:
                delay_samples = int(round(delay_sec * sample_rate))
                tail = delay_samples * 4
                steps.append(f"""
    {{
        int64_t delay_samples = {delay_samples};
        int64_t tail = {tail};
        int64_t out_n = n + tail;
        double* out_buf = (double*)calloc(out_n, sizeof(double));
        apply_delay(buf, buf, 0, n, 1, out_buf, out_buf, 0, out_n, 1, n, out_n, delay_samples, {feedback!r});
        free(buf);
        buf = out_buf;
        n = out_n;
    }}""")
            delay_code = "".join(steps)

        driver_c = f"""
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <math.h>

extern void run_program(double* allocated, double* aligned, int64_t offset,
                         int64_t size0, int64_t stride0, int64_t total_as_index);
extern void apply_delay(double* ia, double* ial, int64_t ioff, int64_t isz, int64_t ist,
                         double* oa, double* oal, int64_t ooff, int64_t osz, int64_t ost,
                         int64_t in_n, int64_t out_n, int64_t delay_samples, double feedback);

static void write_wav(const char* path, const int16_t* pcm, size_t n, int sample_rate) {{
    FILE* f = fopen(path, "wb");
    uint32_t data_bytes = (uint32_t)(n * sizeof(int16_t));
    uint16_t num_channels = 1, bits_per_sample = 16;
    uint32_t byte_rate = sample_rate * num_channels * bits_per_sample / 8;
    uint16_t block_align = num_channels * bits_per_sample / 8;
    uint32_t riff_size = 36 + data_bytes;
    uint32_t fmt_size = 16;
    uint16_t audio_format = 1;
    uint32_t sr = sample_rate;
    fwrite("RIFF", 1, 4, f); fwrite(&riff_size, 4, 1, f); fwrite("WAVE", 1, 4, f);
    fwrite("fmt ", 1, 4, f); fwrite(&fmt_size, 4, 1, f); fwrite(&audio_format, 2, 1, f);
    fwrite(&num_channels, 2, 1, f); fwrite(&sr, 4, 1, f); fwrite(&byte_rate, 4, 1, f);
    fwrite(&block_align, 2, 1, f); fwrite(&bits_per_sample, 2, 1, f);
    fwrite("data", 1, 4, f); fwrite(&data_bytes, 4, 1, f);
    fwrite(pcm, sizeof(int16_t), n, f);
    fclose(f);
}}

int main(int argc, char** argv) {{
    const char* out_path = argc > 1 ? argv[1] : "output.wav";
    int64_t n = {total_samples};
    double* buf = (double*)calloc(n, sizeof(double));

    run_program(buf, buf, 0, n, 1, n);
{delay_code}

    double peak = 0.0;
    for (int64_t i = 0; i < n; i++) {{ double a = fabs(buf[i]); if (a > peak) peak = a; }}
    if (peak > 1e-9) {{
        double scale = 0.95 / peak;
        for (int64_t i = 0; i < n; i++) buf[i] *= scale;
    }}

    int16_t* pcm = (int16_t*)malloc(n * sizeof(int16_t));
    for (int64_t i = 0; i < n; i++) {{
        double v = buf[i];
        if (v > 1.0) v = 1.0;
        if (v < -1.0) v = -1.0;
        pcm[i] = (int16_t)lround(v * 32767.0);
    }}

    write_wav(out_path, pcm, n, {sample_rate});
    printf("wrote %s (%lld samples, %.2f sec) [MLIR backend]\\n", out_path, (long long)n, (double)n / {sample_rate});
    free(buf); free(pcm);
    return 0;
}}
"""
        with open(driver_path, "w") as f:
            f.write(driver_c)

        r = subprocess.run(
            ["gcc", "-no-pie", driver_path, obj_path, "-o", exe_path, "-lm"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise MlirBackendError(f"gcc link failed:\n{r.stderr}")

        r = subprocess.run([exe_path, out_wav_path], capture_output=True, text=True)
        if r.returncode != 0:
            raise MlirBackendError(f"compiled binary failed to run:\n{r.stderr}")
        return r.stdout.strip()