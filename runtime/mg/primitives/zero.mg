# ============================================================================
# PRIMITIVE: ZERO  ([X] := 0, unconditional)      -- self-developed
# ============================================================================
# Force variable X to all-zero trits regardless of its current value.
#
# Algebra (per-trit column maps chosen by loading A with a CONk first):
#   f1 = crazy_trit(A=1, .) : {0,1}->0, 2->2      (ROT CON1 ; OPR X)
#   f2 = crazy_trit(A=2, .) : swap(1,2), fix 0    (ROT CON2 ; OPR X)
#   f0 = crazy_trit(A=0, .) : {0,1}->1, 2->2      (ROT CON0 ; OPR X)
# Composition  f1 then f2 then f1  maps every trit -> 0:
#   x --f1--> {0,1}->0, 2->2  --f2--> 0->0, 2->1  --f1--> {0,1}->0  = 0
#
# Cost: 6 instructions.  Clobbers: A.  Preserves: CONk.
#
ROT CON1
OPR X
ROT CON2
OPR X
ROT CON1
OPR X
# Verified: t_zero.mg  (VAR V=12345 -> zeroed -> OUTPUT 0x00).  py==C.
#
# --------------------------------------------------------------------------
# RELATED: SET_C1  ([X] := all-ones = 1743392200)
#   Same idea, last map is f0 instead of f1:  f1 then f2 then f0  -> all 1.
#     ROT CON1 ; OPR X ; ROT CON2 ; OPR X ; ROT CON0 ; OPR X
#   Verified: t_setc1.mg (OUTPUT 0xC8 = C1 mod 256).  py==C.
#
# LOAD_CONST (compile-time constant K into a variable): just declare it,
#   `VAR X = K`  -- the .mg VAR initializer sets the memory cell directly,
#   no runtime code needed. For a *runtime* reset-to-K, ZERO then build the
#   trits with position-dependent constant OPRs (see normalize_switch.mg for
#   the position-dependent-constant technique).
