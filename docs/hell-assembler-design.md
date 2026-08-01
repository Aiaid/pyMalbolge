# HeLL Assembler Design Document (Python Implementation)

> [中文](hell-assembler-design.zh.md) | **English**

> Goal: implement a HeLL → Malbolge assembler in pyMalbolge, behavior-compatible with LMAO v0.6.0.
> Basis: `docs/hell-spec.md` (language spec) and `docs/lmao-internals.md` (LMAO algorithm analysis).
> Status: design draft, pending review. 2026-07-20.

## 1. Goals and Scope

- **In scope**: a complete HeLL front end (lexical/syntax/semantic analysis) + LMAO-compatible layout
  and bootstrap code generation, producing original Malbolge (10 trits) programs executable by
  pyMalbolge / the reference interpreter.
- **Acceptance criteria**: for the six .hell examples in `test/fixtures/hell/`, the .mal produced by
  this assembler must pass all I/O test cases in `test/test_hell_examples.py` (matching the behavior
  of LMAO's reference output).
- **Out of scope for now** (extension points reserved): a Malbolge20 target (layout and generator
  would need to be parameterized via `MalbolgeConfig`, but the data module's magic constants are
  10-trit-specific and would need to be re-derived for 20-trit); a higher-level language front end
  on top of HeLL (next phase).

## 2. Package Structure

```
malbolge/hell/
├── __init__.py      # assemble(source: str, *, fast=False) -> str, top-level API
├── lexer.py         # context-sensitive tokenizer
├── hast.py          # AST data model (named to avoid clashing with the builtin ast module)
├── parser.py        # recursive-descent parser → AST
├── labels.py        # label table, R_/U_ prefix resolution, virtual RNop synthesis
├── xlat.py          # XLAT2 table, immutable_nops, cycle existence, possible_positions
├── exprs.py         # .DATA expression evaluation (mod 59049 arithmetic, rotation, crazy)
├── layout.py        # three-partition layout, put_all_memcells_together, RQ placement
├── geninit.py       # bootstrap code generator (State simulation, constant synthesis, set_dreg)
├── datamodule.py    # init_datamodule literal prefix + magic constants (from LMAO, see §6)
├── output.py        # denormalize, line wrapping, don't-care padding
└── errors.py        # HellSyntaxError / HellSemanticError / LayoutError (with line numbers)
```

The CLI hooks into the existing entry point: `python -m malbolge asm program.hell -o program.mal`
(`__main__.py` gains a new `asm` subcommand, alongside `run`/`debug`).

## 3. Data Model (hast.py)

Python equivalents of LMAO's structs:

| LMAO | Python | Description |
|---|---|---|
| XlatCycle linked list | `XlatCycle(ops: tuple[int,...], rnop: bool)` | immutable; `rnop=True` means a self-looping Nop |
| DataAtom | `LabelRef(name, kind)`, kind ∈ {PLAIN, R, U}; U carries an `anchor` | |
| DataCell tree | `Expr` recursive node (Const / LabelRef / BinOp / DontCare / NotUsed) | evaluated in exprs.py |
| Code/DataBlock doubly linked list | `Block(kind, offset, cells: list[Cell], labels: dict[str,int])` | the index into cells is the offset within the block |
| LabelTree (BST) | `dict[str, tuple[Block,int]]` | |
| MemoryCell[59049] ×4 | `Layout` class: `usage: bytearray(59049)` + `cells: dict[int, Cell]` | the usage enum mirrors LMAO's six states |
| State/Module/Cell | `GenState` (dataclass): A, D (module, pos), a mirror of module cell values | geninit.py |

## 4. Pipeline

```
source ──lexer──> tokens ──parser──> AST(blocks, labels)
  ──labels──> prefix resolution + virtual RNop synthesis
  ──xlat──> possible_positions[94] + needs_initialization for each code block
  ──routing──> fixed(.OFFSET) / preinitial(embeddable) / toinitial(constructed at runtime)
  ──layout──> merge the three partitions + RQ placement (size-estimation loop)
  ──exprs──> data cell evaluation (label addresses now fixed)
  ──geninit──> normalized bootstrap code (State simulation)
  ──output──> denormalize + prefix/RQ/padding → .mal text
```

Two global loops, consistent with LMAO:
- **Size-estimation loop**: bootstrap code length affects RQ position, RQ position affects layout,
  and layout affects bootstrap code length. We follow LMAO's "estimate → fail → retry with increment"
  approach (initial value uses the same heuristic as LMAO, increment of 32; this could later be
  optimized to a binary search, but before M4 we keep it in sync with LMAO to support
  cross-checking).
- **fast mode**: uses the full memory directly, falling back to normal mode on failure (corresponds
  to `-f`).

## 5. Milestones and Validation

Each milestone has its own independent cross-checking method; we avoid a "big bang" integration at
the end:

| Milestone | Content | Validation |
|---|---|---|
| **M1 Front end** | lexer + parser + AST | all six fixtures parse successfully; block count/cell count/label set cross-checked against LMAO's `-d` debug output; unit tests for error cases (full list in spec §3.5) |
| **M2 Semantic layer** | prefix resolution, xlat existence, expression evaluation | xlat: assert consistency with the C version by enumerating all 94 residues × common cycles (a one-off C driver can be written to export a gold-standard table); expressions: hand-computed test cases + edge cases (mod, negative-number wraparound, rotation-overflow warnings) |
| **M3 Layout** | three partitions, merging, RQ | item-by-item diff of label addresses/partition boundaries against LMAO's `-d` output |
| **M4 Bootstrap generator** | datamodule, State, constant synthesis, single-cell driver | **Byte-level cross-checking**: for the same .hell input, diff our .mal against LMAO's .mal byte by byte (should be fully identical when the algorithm is copied faithfully and the greedy ordering matches; any diff is a bug signal) |
| **M5 Integration** | output, CLI, end to end | `test_hell_examples.py` parameterized to run against "this assembler's output"; all six examples pass I/O |
| **M6 (future)** | Malbolge20 parameterization | requires re-deriving the data module for 20-trit first; a separate project |

**General validation principle**: M4 targets byte-level identity (the strongest proof of correctness
— a diff is itself the verification); wherever an LMAO behavior depends on C undefined behavior and
cannot be replicated, we fall back to behavioral equivalence (I/O cross-checking) and record the
deviation.

## 6. Key Design Decisions

1. **Byte-level compatibility first** (M4): copy the algorithm and greedy ordering faithfully so
   output is byte-identical to LMAO's. This reduces "is the assembler correct?" to a `diff`,
   dramatically lowering debugging cost. Once achieved, subsequent optimizations (better layout,
   shorter initialization) build on top of this byte-level baseline, guarded by behavioral
   cross-checking.
2. **Licensing (pending confirmation from the project owner)**: the init_datamodule prefix string
   and magic constants in `datamodule.py` would need to be copied byte-for-byte from LMAO
   (GPL-3.0), and the layout/generator algorithms would also be line-for-line ports — the
   `malbolge/hell/` subpackage would in substance be a derivative work of LMAO. Options:
   a) license the subpackage separately under GPL-3.0 (the repository becomes mixed-license, which
   would need to be documented in the README);
   b) relicense the entire project under GPL-3.0;
   c) re-derive the data module and initialization strategy independently (substantial effort, and
   it would forfeit byte-level cross-checking).
   **Option a is suggested**; this needs confirmation before implementation begins.
3. **Diagnostics stricter than LMAO**: division by zero → an explicit error (LMAO treats this as
   UB); a label pointing at `?-` → an error (LMAO only warns and may crash); all errors carry line
   numbers. Where LMAO is lenient, we stay compatible: a rotation amount ≥10 is taken mod + a
   warning (same as LMAO).
4. **10-trit constants do not reuse core.py's parameterized version**: geninit internally has many
   10-trit-specific magic values; it uses this package's own constants directly (POW10, etc.)
   rather than falsely presenting itself as "already parameterized." True parameterization is left
   to M6.
5. **Performance**: at a scale of 59049 cells, pure Python is sufficient; no premature optimization.

## 7. Risks

| Risk | Mitigation |
|---|---|
| gen_init state simulation has subtle deviations from the C version (top of the difficulty list) | M4 byte-level cross-checking + tackle fixtures in ascending order of size (simple_hello → adder, 55KB); if necessary, add print patches to LMAO to export intermediate State traces for cross-checking |
| Layout off-by-one errors (second on the difficulty list) | M3 cross-checks label addresses against `-d` debug files |
| C undefined behavior (`%= C2` boundary, division by zero) unexpectedly depended on by examples | first replicate C's actual behavior; concentrate deviation points in one place in exprs.py, with comments |
| Size-estimation loop fails to converge / is slow | start with the same parameters as LMAO; tune only after all tests are green |
