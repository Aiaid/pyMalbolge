# REPEAT { IF { REPEAT { SWITCH { CASE1: REPEAT { OUTPUT } } } } }
VAR X = 300
FLAG F = TRUE
DEF MAIN
  REPEAT 2
    IF F
      REPEAT 3
        SWITCH X
        CASE0
          OUTPUT
        CASE1
          REPEAT 2
            OUTPUT
          END
        CASE2
          OUTPUT
        END
      END
    ELSE
      OUTPUT
    END
  END
END
