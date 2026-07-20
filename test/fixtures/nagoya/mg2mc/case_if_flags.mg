# IF/ELSE, SET/RESET/FLIP on a user flag, empty ELSE branch.
FLAG F = TRUE
DEF MAIN
  IF F
    OUTPUT
  ELSE
    INPUT
  END
  RESET F
  FLIP F
  SET F
END
