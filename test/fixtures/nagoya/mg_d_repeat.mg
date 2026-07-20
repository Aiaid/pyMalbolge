# Control-flow: REPEAT/BREAK. NOTE: `ROT X` rotates variable X in place
# (writes the rotated value back to X as well as A), so re-executing ROT
# on the same variable inside a loop changes its value each iteration.
# To output 'A' repeatably, ROT once before the loop and then only
# OUTPUT (which does not mutate A) inside REPEAT.
VAR A = 195   # 3*'A' (65)
DEF MAIN
  ROT A
  REPEAT 3
    OUTPUT
  END
  REPEAT INF
    OUTPUT
    BREAK
  END
END
