# Cross-routine variable reference X@SUB (forward ref to a var declared later
# in a PROTO'd routine) plus PROTO/CALL/RETURN.
PROTO SUB
DEF MAIN
  ROT X@SUB
  CALL SUB
END
DEF SUB
  VAR X = 42
  OPR X
  RETURN
END
