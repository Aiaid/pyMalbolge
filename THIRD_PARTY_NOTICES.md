# Third-party notices

pyMalbolge's own license is in `LICENSE`. The following upstream MIT
copyright and permission notices are preserved verbatim in `licenses/` and
included in both source and wheel distributions.

- `malbolge/compiler/c2mg.py` ports Nagoya's highlevel compiler:
  https://git.trs.css.i.nagoya-u.ac.jp/malbolge/highlevel
  See `licenses/nagoya-highlevel.txt`.
- `malbolge/compiler/mg2mc.py` ports Nagoya's ternary translator:
  https://git.trs.css.i.nagoya-u.ac.jp/malbolge/ternary
  See `licenses/nagoya-ternary.txt`.
- `malbolge/compiler/mc2mb.py` ports Nagoya's lowass assembler:
  https://git.trs.css.i.nagoya-u.ac.jp/malbolge/lowass
  See `licenses/nagoya-lowass.txt`.
- The Malbolge20 implementation and reference verification use algorithms
  and semantics from Nagoya's interpreter:
  https://git.trs.css.i.nagoya-u.ac.jp/malbolge/malbolge20-interpreter
  See `licenses/nagoya-malbolge20-interpreter.txt`. Its upstream notice says
  "Malbolge20/lowass"; that wording is retained unchanged.

The repository's optional `test/fixtures/hell/` LMAO examples have separate
GPL-3.0 provenance documented in that directory. Those fixtures and their
dependent test are excluded from source and wheel distributions, remain
unchanged in the repository, and are not covered by the project's MIT notice.
