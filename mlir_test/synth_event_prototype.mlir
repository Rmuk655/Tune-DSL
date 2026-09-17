// Prototype: ONE generic, parameterized synth_event function (not one
// per note) with runtime waveform dispatch via scf.index_switch.
func.func @synth_event(%buffer: memref<?xf64>, %total_samples: index,
                        %freq: f64, %start_sample: index, %n_samples: index,
                        %waveform_id: index, %velocity: f64) {
  %c0 = arith.constant 0 : index
  %c1 = arith.constant 1 : index

  // hi = min(n_samples, total_samples - start_sample)
  %remaining = arith.subi %total_samples, %start_sample : index
  %hi_cmp = arith.cmpi slt, %n_samples, %remaining : index
  %hi = arith.select %hi_cmp, %n_samples, %remaining : index

  %sample_rate = arith.constant 44100.0 : f64
  %sample_rate_idx = arith.constant 44100 : index

  // fade_samples = min(220, n_samples/2)   (0.005*44100 = 220.5 -> 220 truncated)
  %fade_const = arith.constant 220 : index
  %n_half = arith.divsi %n_samples, %c1 : index  // placeholder, real divide by 2 below
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

      // absolute sample index, used by noise
      %abs_idx = arith.addi %s, %start_sample : index
      %abs_idx_i64 = arith.index_cast %abs_idx : index to i64
      %abs_idx_i32 = arith.trunci %abs_idx_i64 : i64 to i32

      %wave = scf.index_switch %waveform_id -> f64
      case 0 {
        // sine
        %two_pi = arith.constant 6.283185307179586 : f64
        %angle = arith.mulf %phase, %two_pi : f64
        %v = math.sin %angle : f64
        scf.yield %v : f64
      }
      case 1 {
        // square: 1 - 2*floor(2*phase)
        %two = arith.constant 2.0 : f64
        %scaled = arith.mulf %phase, %two : f64
        %floored = math.floor %scaled : f64
        %term = arith.mulf %floored, %two : f64
        %one = arith.constant 1.0 : f64
        %v = arith.subf %one, %term : f64
        scf.yield %v : f64
      }
      case 2 {
        // saw: 2*phase - 1
        %two = arith.constant 2.0 : f64
        %scaled = arith.mulf %phase, %two : f64
        %one = arith.constant 1.0 : f64
        %v = arith.subf %scaled, %one : f64
        scf.yield %v : f64
      }
      case 3 {
        // triangle: 2*|2*phase-1| - 1
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
        // pulse: 1 - 2*min(1, floor(4*phase))
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
        // noise: triple32 hash of the absolute sample index (must match
        // reference.py's _hash_u32 bit-for-bit -- see codegen_mlir.py)
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

      // branchless envelope (matches codegen.py's C++ backend exactly)
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
