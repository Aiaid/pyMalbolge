# ============================================================================
# PRIMITIVE: IS_ZERO  (flag := (X == 0))          -- self-developed
# ============================================================================
# Detect whether X is all-zero, WITHOUT the official add/compare machinery,
# using a branchless OR-reduction of X's 20 trits into a single trit, then
# ONE (single-shot) SWITCH.  X is preserved.
#
# WHY a custom fold: the crazy table has NO idempotent trit (crazy_trit(t,t)
# is never t), so a tree "OR of Y with rot(Y)" reduction is impossible. A
# LINEAR fold works instead. Requirements found by exhaustive trit search
# (see tests/mgsim.py methodology):
#   init  ACC := 0
#   per trit y of X (LSB first):  ACC := postmap( crazy_trit(ACC, premap(y)) )
#     premap = r0 . r0 = (0,1,1)   -- applied to A via two zero-cell OPRs
#     postmap = f2,f0,f2 = (2,1,2) -- applied to ACC via three CONk-column OPRs
#   Result: ACC trit0 == 1  iff  X == 0 ;  ACC trit0 in {0,2}  iff  X != 0.
# Then NORMALIZE_FOR_SWITCH(ACC) + SWITCH: CASE1 => zero, CASE0/CASE2 => nonzero.
#
# Register/scratch convention (all VARs):
#   X   input (preserved)         ACC = 0   accumulator
#   ZC1 = 0, ZC2 = 0  zero scratches (destroyed+restored each iteration)
#   K1 = 1743392201, K3 = 2   (for NORMALIZE_FOR_SWITCH)
#
# Cost: 520 instr for the fold + 14 for normalize + the SWITCH.  ~13s in
# pyMalbolge, ~0.9s in the C reference. Clobbers A, ACC, ZC1, ZC2. Preserves X.
#
# The fold BODY, repeated 20 times (see tests/t_iszero_*.mg for the full,
# pipeline-verified program that wraps this with normalize+switch+output):
#
#   # read X -> A
#   ROT CON2 / OPR X / ROT CON2 / OPR X
#   # premap A := r0(r0(A))     (two all-zero scratch cells)
#   OPR ZC1 / OPR ZC2
#   # fold:  ACC := crazy(ACC, A)
#   OPR ACC
#   # postmap ACC := f2,f0,f2
#   ROT CON2 / OPR ACC / ROT CON0 / OPR ACC / ROT CON2 / OPR ACC
#   # restore ZC1 := 0 and ZC2 := 0  (ZERO macro, each 6 instr)
#   ROT CON1 / OPR ZC1 / ROT CON2 / OPR ZC1 / ROT CON1 / OPR ZC1
#   ROT CON1 / OPR ZC2 / ROT CON2 / OPR ZC2 / ROT CON1 / OPR ZC2
#   # advance to next trit
#   ROT X
#
# Verified through the pipeline (py==C):
#   X=0 -> zero; X in {1,2,3,59049,3^10,C2,1162467007,...} and EVERY
#   single-trit value (each of 20 positions, values 1 and 2) -> nonzero.
#
# NOTE: the official toolchain also gives you "== 0" for free by compiling
#   `if (x == 0) ...` (see ../official/eq.c) -- that path is cheaper and is the
#   recommended one for a real compiler. This primitive is the from-scratch
#   proof that judgement is reachable with only crazy+rotate.
