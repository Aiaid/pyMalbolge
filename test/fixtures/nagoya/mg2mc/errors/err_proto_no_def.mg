# PROTO without a matching DEF: upstream SIGSEGVs; Python raises Mg2McError.
PROTO FOO
DEF MAIN
  CALL FOO
END
