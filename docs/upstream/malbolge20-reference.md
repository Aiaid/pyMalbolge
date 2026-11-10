# Malbolge20: machine model and toolchain layers

> **English** | [中文](malbolge20-reference.zh.md)
>
> Reference checked on 2026-10-27. This is a project reference, not a new
> language specification. Machine details below follow the published C
> interpreter at upstream revision `2b42f4817afecca6b4c4f7374e21a399b6488e31`;
> implementation edge cases are identified separately.

## What the extension changes

Malbolge20 expands Malbolge's words and addresses from ten ternary digits
(trits) to twenty. The [official project page](https://malbolge20.gitlab.io/index-en.html)
lists the 2013 technical report *Malbolge with 20trits word length and its
programming support tool* by Tatsuki Kato, Masahiko Sakai, Toshiki Sakabe,
Keiichirou Kusakari and Naoki Nishida. The
[Nagoya University repository record](https://nagoya.repo.nii.ac.jp/records/21421)
gives IEICE Technical Report 113(160), 73–78 (July 2013), with report
identifiers SS2013-25 / KBSE2013-25. The official landing page instead lists
issue 159; this document follows the institutional record and records the
discrepancy rather than silently combining the citations. The project page
also links the interpreter, assembly-language definition and compiler sources.

| Property | Original Malbolge | Malbolge20 |
|---|---:|---:|
| Trits per word and address | 10 | 20 |
| Addressable cells | `3^10 = 59,049` | `3^20 = 3,486,784,401` |
| Word/address range | `0…59,048` | `0…3,486,784,400` |
| Multiplier used in right rotation | `3^9 = 19,683` | `3^19 = 1,162,261,467` |

These are counts of logical cells and values. They do not specify a host
allocation size, a source-file size in gigabits, or an amount of available RAM.
The reference interpreter allocates memory in blocks as needed. Its allocation
strategy implements the fixed address space; it does not make that address
space unbounded. See the reference's `main`, `mem_manage` and `increment`.
([C source](https://gitlab.com/malbolge20/malbolge20_creator/-/blob/2b42f4817afecca6b4c4f7374e21a399b6488e31/runtime/malbolge20-interpreter/malbolge20.c))

## Registers, source loading and memory

Code and data occupy the same memory. The registers are `A` (accumulator),
`C` (code pointer), and `D` (data pointer), initially zero. `[x]` below means
the contents of memory cell `x`; register assignments and memory writes are
distinct operations.

The C loader skips whitespace and loads the remaining source characters
consecutively from address zero as their character codes. At each source
position it accepts only printable ASCII characters whose position-dependent
decoding denotes one of the eight named instructions. Thus a source character
is not a fixed opcode independent of its address. The rest of memory is
initialized recursively:

```text
[i] = crazy([i-1], [i-2])
```

Here `crazy(x, y)` uses the operand order defined below. Initial contents are
determined by the loaded program, rather than all being zero. The C loader
rejects inputs with fewer than two non-whitespace characters; its diagnostic
calls these empty inputs. Do not infer one-character-program behavior from
the recurrence. These loading details come from the reference's `main` and
`make_init_mem`, rather than from the compiler's intermediate languages.
([C source](https://gitlab.com/malbolge20/malbolge20_creator/-/blob/2b42f4817afecca6b4c4f7374e21a399b6488e31/runtime/malbolge20-interpreter/malbolge20.c))

## Decoding and instruction cycle

The C reference checks that `[C]` is in `33…126`, then obtains a normalized
instruction character using its table `xlat1`:

```text
xlat1[([C] - 33 + C) mod 94]
```

`C` here is the full address, including the reference implementation's block
number. The equivalent residue `([C] + C) mod 94` gives this instruction
table. The middle column is the decoded character, not necessarily the
character written at that source position.

| Residue | Decoded character | Effect before the common update |
|---:|:---:|---|
| 4 | `i` | `C := [D]` |
| 5 | `<` | Output the accumulator as a byte in the C reference |
| 23 | `/` | Read input into `A` |
| 39 | `*` | `A := [D] := rotate([D])` |
| 40 | `j` | `D := [D]` |
| 62 | `p` | `A := [D] := crazy(A, [D])` |
| 68 | `o` | No operation |
| 81 | `v` | Halt immediately |

At runtime, other decoded characters also perform no operation. Among these
no-operation forms, the loader accepts only the designated instruction `o`
for a no-operation source cell. For a non-halting instruction, the reference
then applies its
94-character replacement table `xlat2` to the cell at the **current** `C`,
and increments both `C` and `D`, with wraparound modulo `3^20`:

```text
[C] := xlat2[[C] - 33]
C := (C + 1) mod 3^20
D := (D + 1) mod 3^20
```

The order matters. A jump changes `C` before this replacement: it replaces
the cell at the address loaded from `[D]`, then fetches the next instruction
at that address plus one. It does not generally replace the original jump
cell. Loading `D` is likewise followed by the common increment. These are
the same decoding and replacement mechanisms as original Malbolge; widening
the words does not add a new opcode or replacement table.
([Reference `exec` and tables](https://gitlab.com/malbolge20/malbolge20_creator/-/blob/2b42f4817afecca6b4c4f7374e21a399b6488e31/runtime/malbolge20-interpreter/malbolge20.c))

**Implementation boundary:** the C reference reports an error when the cell
fetched for execution is outside printable ASCII. Its later `xlat2` lookup
does not check the index again after a jump or memory write. Consequently,
that source does not define safe behavior for every possible non-printable
replacement target. pyMalbolge guards this later lookup; that guard is an
implementation choice, not evidence of a language-wide rule for those cases.

## Ternary operations and compatibility

Right rotation moves the lowest trit into the highest position:

```text
rotate(x) = x div 3 + (x mod 3) × 3^19
```

The crazy operation applies this table independently to each of the twenty
trit positions. Rows select a trit of the **second** operand `y`; columns
select a trit of the **first** operand `x`.

| `crazy(x, y)` | `x = 0` | `x = 1` | `x = 2` |
|---|---:|---:|---:|
| `y = 0` | 1 | 0 | 0 |
| `y = 1` | 1 | 0 | 2 |
| `y = 2` | 2 | 2 | 1 |

The table is not commutative. The arithmetic instruction uses
`crazy(A, [D])`, while initialization uses `crazy(previous, second_previous)`.
The C implementation's `op(x, y)` processes two trits at a time through an
equivalent 9-by-9 table.
([Reference `op` and rotation](https://gitlab.com/malbolge20/malbolge20_creator/-/blob/2b42f4817afecca6b4c4f7374e21a399b6488e31/runtime/malbolge20-interpreter/malbolge20.c))

Programs for ten-trit Malbolge are not generally compatible with Malbolge20,
even if their source passes both loaders. For example, rotating `1` gives
`19,683` at ten trits and `1,162,261,467` at twenty. Also, `crazy(0, 0)`
produces a word of all ones: `29,524` at ten trits, versus `1,743,392,200`
at twenty. Leading zero trits still participate in the operation. These
examples follow directly from the rotation formula and trit table; they are
not benchmark results or a claim that every program behaves differently.

## Input, output and end of input

The C reference reads with `getc` and writes with `putc`. On byte-oriented
ASCII systems, output is the low byte of `A` (`A mod 256`), and an input
byte becomes `A`. At EOF it assigns **`59049 = 3^10`**, rather than the
twenty-trit all-twos value `3^20 - 1 = 3,486,784,400`. The source also
contains host-newline adaptations. Its EOF constant should therefore be
documented as reference behavior, rather than guessed from the word width.
([Reference input/output cases](https://gitlab.com/malbolge20/malbolge20_creator/-/blob/2b42f4817afecca6b4c4f7374e21a399b6488e31/runtime/malbolge20-interpreter/malbolge20.c))

In pyMalbolge, the byte-oriented `run20` API and batch CLI use that sentinel
by default. `eof="stop"` is an explicit host convenience that stops when
input is exhausted. The legacy string-returning `eval20` API defaults to
that convenience and accepts character-based input; it is not a definition
of the reference machine's byte I/O. See
[`malbolge20.py`](../../malbolge/malbolge20.py) and
[`core.py`](../../malbolge/core.py).

## Bounded memory and Malbolge Unshackled

Twenty trits give a much larger but still fixed memory. With finitely many
cells, finitely many values per cell and finitely many register values,
the machine has only finitely many internal configurations. Without adding
an external storage mechanism, this is a bounded-storage machine, not a
Turing-complete machine with an unbounded work tape. This is a consequence
of the fixed machine model, not an unresolved claim about how large
`3^20` happens to be.

Malbolge Unshackled is a separate variant. Its operation is designed around
unbounded addressing and a rotation width that can grow during execution;
it is not Malbolge20 with a larger fixed constant. The
[Unshackled tool/reference page](https://lutter.cc/unshackled/) links the
language specification and creator's reference interpreter and describes
the growing rotation width. Do not infer Unshackled Unicode I/O or
arithmetic semantics from Malbolge20's C interpreter.

## Assembly and compiler layers

The current [canonical toolchain README](https://gitlab.com/malbolge20/malbolge20_creator/-/blob/2b42f4817afecca6b4c4f7374e21a399b6488e31/README.md)
describes this route:

```text
C-like source (.c)
  → pseudo-instruction sequences with control (.mg)
  → low-level assembly language, LAL (.mc)
  → memory image (.data)
  → executable Malbolge20 source (.mb)
```

`highlevel` supplies the C-like frontend; `ternary` lowers `.mg` to LAL;
`lowass` constructs a memory image and an initialization program; the
interpreter executes the resulting `.mb`. The
[official LAL definition](https://malbolge20.gitlab.io/20trits_lal/lal-def-en.html)
describes labels, units, routines, flags and recovery instructions for
assembling self-modifying code. These constructs belong to an assembly
language, rather than being additional machine instructions in Malbolge20.

pyMalbolge provides another frontend, from a documented subset of Python,
and Python implementations of the lower compiler stages. Its C route passes
through the C-like subset; the direct route produces `.mg` without that
stage. Structured LAL and memory-image interfaces can replace serialized
intermediate files. The result still runs on the Malbolge20 machine.
Python functions, arithmetic helpers and decimal I/O are compiler/runtime
features, not additions to the language's eight named instructions. For
accepted Python syntax and divergences from CPython, use the
[Python subset specification](../specs/python-subset-spec.md); for the
intermediate language, use the [`.mg` specification](../specs/mg-spec.md).

## Evidence and limits

The canonical source revision above was read directly on 2026-10-27. Its
interpreter file has SHA-256
`0ea5d2cfd8e597256f91bae3ea505f2f8467e3704e5c362b24fc91b56b9782b0`,
also the content pinned by this project's independent reference gate.
The numeric examples and opcode residues were checked against the source
tables and the current project implementation; no runtime performance or
full conformance claim is made here. The official landing page supplies the
publication title and author names, while the institutional record supplies
the issue/date/report identifiers; this document does not claim a fresh
reading of the 2013 paper's full text. See
[the reference setup](toolchain-guide.md) for acquiring the independently
pinned C reference.
