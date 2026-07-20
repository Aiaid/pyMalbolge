# Nagoya Malbolge20 test fixtures

`hello20.mb` is the sample program from the Nagoya University Malbolge20
reference interpreter:

- **Source**: https://git.trs.css.i.nagoya-u.ac.jp/malbolge/malbolge20-interpreter
  (`sample/hello20.mb`)
- **License**: MIT (Copyright (c) Nagoya Univ.)
- **Project page**: https://www.trs.css.i.nagoya-u.ac.jp/projects/Malbolge/

It was produced by the Nagoya LAL-for-Malbolge20 toolchain and prints
`HelloWorld` (46,417 steps). It serves as a conformance check that
pyMalbolge's Malbolge20 interpreter (EOF value, block-based sparse memory
initialization) matches the reference implementation.
