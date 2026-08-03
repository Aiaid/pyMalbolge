# Minimal pipeline smoke test: a bare OUTPUT with no preceding ROT, so the
# byte emitted is whatever the bootstrap left in the A register -- undefined,
# and it does differ between mg2mc code-generation styles (0xDE under
# op_style=cluster, 0x9E under inline).  Exercises the pipeline, not a value:
# do not use this fixture for cross-style output comparison.
DEF MAIN
  OUTPUT
END
