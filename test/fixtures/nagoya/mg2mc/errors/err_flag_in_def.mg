# FLAG declared inside a DEF body (only allowed at top level) -> syntax error.
DEF MAIN
  FLAG F = TRUE
  OUTPUT
END
