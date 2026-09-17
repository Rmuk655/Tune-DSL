module {
  llvm.func @fill_sine(%arg0: !llvm.ptr, %arg1: !llvm.ptr, %arg2: i64, %arg3: i64, %arg4: i64, %arg5: f64, %arg6: f64) {
    %0 = llvm.mlir.undef : !llvm.struct<(ptr, ptr, i64, array<1 x i64>, array<1 x i64>)>
    %1 = llvm.insertvalue %arg0, %0[0] : !llvm.struct<(ptr, ptr, i64, array<1 x i64>, array<1 x i64>)> 
    %2 = llvm.insertvalue %arg1, %1[1] : !llvm.struct<(ptr, ptr, i64, array<1 x i64>, array<1 x i64>)> 
    %3 = llvm.insertvalue %arg2, %2[2] : !llvm.struct<(ptr, ptr, i64, array<1 x i64>, array<1 x i64>)> 
    %4 = llvm.insertvalue %arg3, %3[3, 0] : !llvm.struct<(ptr, ptr, i64, array<1 x i64>, array<1 x i64>)> 
    %5 = llvm.insertvalue %arg4, %4[4, 0] : !llvm.struct<(ptr, ptr, i64, array<1 x i64>, array<1 x i64>)> 
    %6 = llvm.mlir.constant(0 : index) : i64
    %7 = llvm.mlir.constant(8 : index) : i64
    %8 = llvm.mlir.constant(1 : index) : i64
    %9 = llvm.mlir.constant(6.2831853071795862 : f64) : f64
    llvm.br ^bb1(%6 : i64)
  ^bb1(%10: i64):  // 2 preds: ^bb0, ^bb2
    %11 = llvm.icmp "slt" %10, %7 : i64
    llvm.cond_br %11, ^bb2, ^bb3
  ^bb2:  // pred: ^bb1
    %12 = llvm.sitofp %10 : i64 to f64
    %13 = llvm.fdiv %12, %arg6  : f64
    %14 = llvm.fmul %arg5, %13  : f64
    %15 = llvm.fmul %14, %9  : f64
    %16 = llvm.intr.sin(%15)  : (f64) -> f64
    %17 = llvm.extractvalue %5[1] : !llvm.struct<(ptr, ptr, i64, array<1 x i64>, array<1 x i64>)> 
    %18 = llvm.getelementptr %17[%10] : (!llvm.ptr, i64) -> !llvm.ptr, f64
    llvm.store %16, %18 : f64, !llvm.ptr
    %19 = llvm.add %10, %8 : i64
    llvm.br ^bb1(%19 : i64)
  ^bb3:  // pred: ^bb1
    llvm.return
  }
}

