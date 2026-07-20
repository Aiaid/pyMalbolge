# ============================================================================
# PRIMITIVE: NORMALIZE_FOR_SWITCH                 -- self-developed
# ============================================================================
# SWITCH X in this toolchain branches on the LAST (lowest) trit of X, but ONLY
# works correctly when X's upper 19 trits are all 2 (empirically confirmed:
# raw values with dirty upper trits mis-dispatch or crash; see the "SWITCH
# constraint" note in ../README.md). This macro forces the upper 19 trits of
# a value to 2 while PRESERVING its last trit, so it can then be SWITCHed.
#
# It uses position-dependent constants: the same 4 OPRs act as the identity
# (f2 applied 4x = id) on the last-trit position and as the constant-2 map
# (f1,f2,f0,f2) on every other position.
#   K1 = 1743392201  (upper trits 1, last trit 2)   -- needs VAR K1
#   K3 = 2           (upper trits 0, last trit 2)   -- needs VAR K3
#   C2 loaded via ROT CON2 (upper+last all 2)
# Sequence applies column maps  f_{K1}, f2, f_{K3}, f2  to X.
#
# Cost: 14 instructions.  Clobbers: A.  Destroys X's upper trits (keeps last).
# Requires:  VAR K1 = 1743392201     VAR K3 = 2
#
ROT CON2
OPR K1
ROT CON2
OPR K1
OPR X
ROT CON2
OPR X
ROT CON2
OPR K3
ROT CON2
OPR K3
OPR X
ROT CON2
OPR X
# After this, `SWITCH X / CASE0 / CASE1 / CASE2 / END` dispatches on the
# preserved last trit.  Verified: ns_*.mg over last-trit {0,1,2} with dirty
# upper trits -> always correct case.  py==C.
#
# IMPORTANT: SWITCH consumes the switched cell AS CODE (executing it mutates
# it, Malbolge re-encrypts executed cells). Do NOT OPR-write a cell and then
# SWITCH it more than once expecting the same behavior in a hand-rolled loop;
# the official codegen instead re-derives a dedicated switch cell
# (CONST_3486784398) every pass. See ../README.md "SWITCH mechanics".
