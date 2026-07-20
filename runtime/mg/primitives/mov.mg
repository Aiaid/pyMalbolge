# ============================================================================
# PRIMITIVE: MOV  (DST := SRC, exact copy, SRC preserved)   -- self-developed
# ============================================================================
# Copy the full 20-trit value of SRC into DST.  SRC is left unchanged.
# Needs one scratch variable TMP (clobbered, ends holding r1(SRC)).
#
# Why it is not a one-liner:
#   OPR always mixes A and the memory cell (result = crazy(A,[cell]) written
#   to BOTH). A single OPR into DST cannot ignore DST's old value (the crazy
#   table has no constant column). The ONLY bijective way to inject an
#   A-value into a cell is: preset the cell to C1 (all-ones) and OPR it, which
#   yields r1(x) = swap(0,1) of the A operand. r1 is an involution, so
#   applying it twice (through a TMP hop) reproduces SRC exactly.
#
#   step 1  SET_C1(TMP)                 TMP := 1111...1
#   step 2  READ SRC -> A               A := SRC   (SRC preserved)
#   step 3  OPR TMP                     TMP := r1(SRC)
#   step 4  SET_C1(DST)                 DST := 1111...1
#   step 5  READ TMP -> A               A := r1(SRC)
#   step 6  OPR DST                     DST := r1(r1(SRC)) = SRC
#
# Cost: 22 instructions.  Clobbers: A, TMP.  Preserves: SRC, CONk.
#
# --- step 1: SET_C1(TMP) ---
ROT CON1
OPR TMP
ROT CON2
OPR TMP
ROT CON0
OPR TMP
# --- step 2: READ SRC -> A ---
ROT CON2
OPR SRC
ROT CON2
OPR SRC
# --- step 3: OPR TMP  (TMP := r1(SRC)) ---
OPR TMP
# --- step 4: SET_C1(DST) ---
ROT CON1
OPR DST
ROT CON2
OPR DST
ROT CON0
OPR DST
# --- step 5: READ TMP -> A ---
ROT CON2
OPR TMP
ROT CON2
OPR TMP
# --- step 6: OPR DST  (DST := SRC) ---
OPR DST
# Verified: t_mov.mg  (SRC=1162467007 with low/mid/high trits set; DST dumped
# at rotations 0,7,14 all match SRC, and SRC low byte unchanged).  py==C.
