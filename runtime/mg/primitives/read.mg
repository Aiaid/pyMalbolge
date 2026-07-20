# ============================================================================
# PRIMITIVE: READ  (A := [X], non-destructive)   -- self-developed
# ============================================================================
# Load the value of variable X into the A register WITHOUT changing X.
# This is the fundamental "read a variable" idiom; almost every other
# primitive uses it.
#
# Algebra:
#   * ROT CON2 loads C2 (all-2 trits) into A. C2 is rotation-invariant
#     (rotr(C2)=C2), so ROT CON2 never mutates CON2 -- it is a pure
#     "A := all-twos" load. Same for CON0 (all-0) and CON1 (all-1).
#   * With A = C2, `OPR X` applies the per-trit column map
#         g2(t) = crazy_trit(A=2, t) = swap(1,2), fix 0     (an involution)
#     to X (and leaves the same value in A).
#   * Doing it twice restores X (g2 is self-inverse) and leaves A = [X].
#
# Cost: 4 instructions.  Clobbers: A.  Preserves: X and all CONk.
#
# Sequence (substitute the real variable name for X):
ROT CON2
OPR X
ROT CON2
OPR X
# Verified: t_read.mg  (VAR V=200 -> OUTPUT 0xC8).  py==C.
