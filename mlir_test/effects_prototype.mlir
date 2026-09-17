// lowpass: y[n] = y[n-1] + alpha*(x[n]-y[n-1]).  Sequential -> iter_args.
func.func @apply_lowpass(%buffer: memref<?xf64>, %n: index, %cutoff_hz: f64) {
  %c0 = arith.constant 0 : index
  %c1 = arith.constant 1 : index
  %zero = arith.constant 0.0 : f64
  %cutoff_gt_0 = arith.cmpf ogt, %cutoff_hz, %zero : f64
  scf.if %cutoff_gt_0 {
    %dt = arith.constant 0.0000226757 : f64  // 1/44100
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

// highpass: y[n] = alpha*(y[n-1] + x[n] - x[n-1]). Needs TWO carried values
// (prev_y, prev_x) -> iter_args supports multiple loop-carried values.
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

// distortion: y = tanh(drive*x)/tanh(drive). Elementwise, no iter_args.
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

// delay: y[n] = x[n] + feedback*y[n-delay_samples]. Reads its OWN earlier
// output -- a genuine sequential memory dependency (not iter_args-based,
// since it reads a variable-lag index, not just the previous iteration).
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
