; ModuleID = 'LLVMDialectModule'
source_filename = "LLVMDialectModule"

define void @fill_sine(ptr %0, ptr %1, i64 %2, i64 %3, i64 %4, double %5, double %6) {
  %8 = insertvalue { ptr, ptr, i64, [1 x i64], [1 x i64] } undef, ptr %0, 0
  %9 = insertvalue { ptr, ptr, i64, [1 x i64], [1 x i64] } %8, ptr %1, 1
  %10 = insertvalue { ptr, ptr, i64, [1 x i64], [1 x i64] } %9, i64 %2, 2
  %11 = insertvalue { ptr, ptr, i64, [1 x i64], [1 x i64] } %10, i64 %3, 3, 0
  %12 = insertvalue { ptr, ptr, i64, [1 x i64], [1 x i64] } %11, i64 %4, 4, 0
  br label %13

13:                                               ; preds = %16, %7
  %14 = phi i64 [ %24, %16 ], [ 0, %7 ]
  %15 = icmp slt i64 %14, 8
  br i1 %15, label %16, label %25

16:                                               ; preds = %13
  %17 = sitofp i64 %14 to double
  %18 = fdiv double %17, %6
  %19 = fmul double %5, %18
  %20 = fmul double %19, 0x401921FB54442D18
  %21 = call double @llvm.sin.f64(double %20)
  %22 = extractvalue { ptr, ptr, i64, [1 x i64], [1 x i64] } %12, 1
  %23 = getelementptr double, ptr %22, i64 %14
  store double %21, ptr %23, align 8
  %24 = add i64 %14, 1
  br label %13

25:                                               ; preds = %13
  ret void
}

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare double @llvm.sin.f64(double) #0

attributes #0 = { nocallback nofree nosync nounwind speculatable willreturn memory(none) }

!llvm.module.flags = !{!0}

!0 = !{i32 2, !"Debug Info Version", i32 3}
