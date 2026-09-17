func.func @fill_sine(%buf: memref<8xf64>, %freq: f64, %sample_rate: f64) {
  %c0 = arith.constant 0 : index
  %c8 = arith.constant 8 : index
  %c1 = arith.constant 1 : index
  %two_pi = arith.constant 6.283185307179586 : f64

  scf.for %i = %c0 to %c8 step %c1 {
    %i_idx = arith.index_cast %i : index to i64
    %i_f = arith.sitofp %i_idx : i64 to f64
    %t = arith.divf %i_f, %sample_rate : f64
    %raw = arith.mulf %freq, %t : f64
    %angle = arith.mulf %raw, %two_pi : f64
    %s = math.sin %angle : f64
    memref.store %s, %buf[%i] : memref<8xf64>
  }
  return
}
