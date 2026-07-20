# CALL/RETURN: MAIN calls SUB, which outputs 'X' and returns.
VAR X = 264   # 3*'X' (88)
PROTO SUB
DEF MAIN
  CALL SUB
END
DEF SUB
  ROT X
  OUTPUT
  RETURN
END
