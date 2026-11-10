# Original Malbolge: machine and reference behavior

> **English** | [中文](malbolge-reference.zh.md)
>
> Current reference guide; source and implementation review: 2026-10-27.
> Scope: the original, fixed-width **10-trit** language. This is not a
> specification of Malbolge20 or Malbolge Unshackled.

Malbolge was introduced by Ben Olmstead in 1998 with the stated aim of being
difficult to program. Its specification describes a small ternary machine,
not a conventional assembly language with independent opcodes and operands.
The stored character, its address, and earlier changes to memory jointly
determine execution. The original specification and interpreter explicitly
place themselves in the public domain. [1][2]

## 1. Which source defines which behavior?

The 1998 prose specification and C interpreter disagree in observable ways.
This guide uses the interpreter's input/output instruction mapping, as does
Lou Scheffer's programming analysis, while identifying implementation defects
separately. Calling all behavior of the old C program the language definition
would also include undefined array accesses. [1][2][3]

| Evidence | Useful for | Qualification |
|---|---|---|
| Olmstead's specification, preserved mirror [1] | Machine model, intended source restrictions, operations | Its `<` and `/` descriptions reverse the interpreter's I/O directions |
| Olmstead's C interpreter, preserved mirror [2] | Exact decode, assignment, encryption and increment order | Includes loader and execution defects; host C behavior matters |
| Scheffer's own analysis [3] | Programming techniques and the jump/encryption interaction | Its proposed extensions and informal completeness arguments are distinct from the original machine |
| Esolangs article [4] | Community explanation and links | Secondary summary; not evidence that every implementation behaves identically |
| This checkout's source [5] | Current project API behavior | Project choices do not retrospectively repair the original specification |

This guide does not settle historical priority claims about the first program,
first successful algorithm or exact date of an early demonstration. Such
claims require the corresponding author's original account or artifact.

## 2. State and notation

A **trit** is a base-three digit, 0, 1 or 2. A word contains ten trits and
represents an unsigned integer from 0 to `3^10 - 1 = 59048`. There are exactly
`3^10 = 59049` memory cells, addressed from 0 to 59048. Code and data occupy
the same array; memory is measured in words, not 59,049 eight-bit bytes. [1]

The machine has three word-sized registers, initially zero:

| Register | Role |
|---|---|
| `A` | Accumulator; input, output and results of data operations |
| `C` | Address of the instruction to fetch |
| `D` | Address used by data operations |

Below, `M[x]` is the word stored at address `x`. A value and the cell containing
that value must be distinguished: `D = M[D]` changes a pointer, whereas
`M[D] = value` changes memory. There is no direct instruction for assigning an
arbitrary literal to `A` or an arbitrary memory cell. [1][2]

## 3. Loading and initial memory

Whitespace is removed before positions are assigned. The remaining characters
are stored consecutively beginning at address zero. Under the intended source
rule, each character is graphical ASCII (33–126), and its instruction decoded
at that address must be one of the eight accepted operations. Runtime NOPs
outside the designated source NOP are therefore not freely available as source
characters. The program may occupy at most 59,049 cells. [1][2]

For a source with at least two characters, remaining cells are filled in
ascending address order:

```text
M[i] = crazy(M[i-1], M[i-2])
```

Here `crazy(x, y)` uses `x` as the column operand and `y` as the row operand in
the table below. Operand order matters. The fill is deterministic, not random
and not a zero fill. Each new cell participates in subsequent initialization.
[1][2]

The original recurrence does not specify useful seeds for empty or one-character
sources. The C program reads before the allocated array in these cases, so it
does not supply a portable definition. A one-character halt may appear to work
on a particular host, but initialization occurs before execution. [2]

The old C loader validates graphical characters only inside a range check;
other non-whitespace byte values can pass through without instruction
validation. This is a loader defect, not the intended source alphabet.
Scheffer explicitly discusses using it in an early copy program. [2][3]

## 4. Decoding and instructions

For a graphical word at `M[C]`, define:

```text
r = (M[C] + C) mod 94
```

This is equivalent to the original `xlat1[(M[C] - 33 + C) mod 94]` lookup
followed by dispatch on its operation letter. The letters below are decoded
mnemonics; writing that letter literally into a file does not generally encode
the corresponding operation. [1][2]

| `r` | Mnemonic | Effect before encryption and pointer increments |
|---:|:---:|---|
| 4 | `i` | `C = M[D]` |
| 5 | `<` | Output the low eight bits of `A` on an eight-bit-byte host |
| 23 | `/` | Read a byte into `A`; EOF sets `A = 59048` |
| 39 | `*` | `A = M[D] = rotate(M[D])` |
| 40 | `j` | `D = M[D]` |
| 62 | `p` | `A = M[D] = crazy(A, M[D])` |
| 68 | `o` | No operation |
| 81 | `v` | Halt immediately |

Other residues act as NOPs during execution, but only residue 68 is the accepted
source NOP. At address zero the eight legal graphical source characters are
`' ( > D Q b c u`, corresponding respectively to residues
39, 40, 62, 68, 81, 4, 5, 23. Moving a character one cell changes its decode
residue by one; source positions count after whitespace removal. [2]

The input and output rows follow the **C interpreter**, not the reversed
descriptions in the prose specification. Input EOF is the ten-trit all-twos
value, `2222222222` in base three, not zero or a negative machine word.
EOF does not itself halt execution. Outputting that value on an eight-bit-byte
host emits byte 168 because `59048 mod 256 = 168`. The original C uses standard
I/O and text streams; platform newline conversion is a host concern. [1][2]

## 5. Data operations

Right rotation moves the least significant trit to the most significant
position without changing word width:

```text
rotate(x) = floor(x / 3) + 19683 * (x mod 3)
```

For example, the ten-trit value `0000000001` becomes `1000000000`, or decimal
19683. Ten rotations restore a ten-trit word. [1][2]

The crazy operation applies this lookup independently at all ten positions:

| Trit of second operand `y` / first operand `x` | 0 | 1 | 2 |
|---:|---:|---:|---:|
| 0 | 1 | 0 | 0 |
| 1 | 1 | 0 | 2 |
| 2 | 2 | 2 | 1 |

For `crazy(A, M[D])`, the row is a trit from `M[D]` and the column a trit from
`A`. There is no carry between trits. The function is not commutative:
`crazy(0, 1) = 29524`, whereas `crazy(1, 0) = 29523` for ten-trit words. Leading
zeros are processed too; this is why a calculation on small decimal operands
can produce a large word. [1][2]

## 6. The execution cycle and self-modification

The observable order is important: [2][3]

1. Fetch and decode the word at `C`.
2. Perform the operation. Halt returns immediately.
3. Transform the word at the **current** `C` through the encryption table.
4. Increment both `C` and `D`, wrapping 59048 to zero.
5. Fetch the next instruction.

The encryption table is a fixed permutation of graphical ASCII, indexed by
the current word minus 33. It is distinct from the address-dependent decode
table. Its 94 output characters, in input order from `!` through `~`, are:

```text
5z]&gqtyfr$(we4{WP)H-Zn,[%\3dL+Q;>U!pJS72FhOA1CB6v^=I_0/8|jsb9m<.TVac`uY*MK'X~xDl}REokN:#?G"i@
```

Consequently, re-entering the same address can execute a different operation.
Data operations can also rewrite code when `D` points into a code region.
The original specification's general statement about `A` receiving memory-write
results should not be read as including automatic instruction encryption:
the C interpreter does not copy the encrypted word into `A`. [1][2]

For a jump, step 2 changes `C` before step 3. Encryption therefore applies at
the assigned address, and the next fetch is one cell after that address,
modulo 59049. For example, assigning `C = 100` encrypts `M[100]` and then fetches
at 101. The original jump cell is not automatically encrypted merely because it
was fetched; aliasing can still make addresses coincide. Likewise, assigning
`D = M[D]` is followed by incrementing the newly assigned `D`. [2][3]

Two original C defects must not be folded into a clean pseudocode model:

- Fetching a word outside 33–126 executes `continue` without changing registers
  or memory: the interpreter spins. The prose specification instead says to
  end execution.
- The post-operation encryption lookup has no range guard. A jump or data write
  can make its index invalid, causing undefined C behavior rather than a
  portable additional instruction or guaranteed halt. [1][2]

## 7. Computational limits

The original machine has a fixed amount of internal storage. For well-defined
machine states, its memory and registers have at most
`59049^(59049 + 3)` combinations. This elementary bound counts internal state,
not an unbounded host log, output buffer or externally supplied input stream.
With no further input, repeating an internal state repeats future behavior.
The bound explains why the original fixed-memory machine is not a universal
Turing machine with an unbounded read/write tape. It does not prevent long
computations, loops or useful algorithms. [1][3]

Arbitrary loops alone do not establish that a machine is more powerful than a
linear bounded automaton; linear bounded automata can loop too. A claim about
Turing completeness must identify where unbounded storage comes from. Scheffer's
Malbolge-T changes the external I/O model; Malbolge20 enlarges the finite word
and address widths; Malbolge Unshackled changes the storage model. These are
separate languages or proposals, not evidence that original Malbolge has
unbounded memory. [3][4]

## 8. This project's interfaces

These are implementation details, not new language rules. [5]

```bash
uv run python -m malbolge examples/hello.mal
uv run python -m malbolge debug examples/hello.mal
```

`malbolge.run(source, input_data=b"", max_steps=..., max_output=...)` executes
the original language with byte output and defaults to the EOF sentinel. Its
`RunResult` records why execution stopped. Invalid instruction fetches stop
with `invalid_instruction`; a range guard skips invalid encryption inputs.
This avoids the old C spin and out-of-bounds lookup, rather than reproducing
their host-dependent consequences.

`run()` uses `parse_source`, which removes space, LF, CR and tab; this is
narrower than C `isspace`. Its validation checks decode residues without a
separate graphical-ASCII restriction. `DenseMemory.initialize_source` reserves
the first two seed cells, zero-filling any missing seeds, then fills from
`max(source_length, 2)`. These choices are defined by this implementation,
not by the underspecified short-source case in the original document.

Legacy `eval()` returns a string and defaults to `eof="stop"`, returning when
its supplied input is exhausted. Use `eof="sentinel"` when the program should
observe EOF. Legacy initialization skips only space and LF, and differs from
the `run()` initializer on short sources. Legacy string input uses character
codepoints; `run()` accepts bytes and encodes text input as UTF-8. Do not mix
these APIs when comparing byte-level behavior.

The Python compiler in this repository targets **Malbolge20**. A compiled
`.mb` file is not automatically an original-Malbolge program; the file suffix
does not identify the word width. The optional native VM and JIT are likewise
Malbolge20 facilities. None changes the original machine described above.

## Sources

1. Ben Olmstead, [1998 Malbolge specification, preserved text](https://esoteric.sange.fi/orphaned/malbolge/malbolge.txt). Original author text; public-domain dedication at its beginning.
2. Ben Olmstead, [original C interpreter, Try It Online mirror](https://raw.githubusercontent.com/TryItOnline/malbolge/master/malbolge.c). Inspect `main`, `exec`, `op`, `xlat1` and `xlat2`. This is a mirror, not a claim that Try It Online designed the language. The local [`ref/mbi.c`](../../ref/mbi.c) is a portability-adjusted copy.
3. Lou Scheffer, [Programming in Malbolge](https://www.lscheffer.com/malbolge.shtml), especially “Jump instructions do not self modify”, “Initializing values”, and the completeness sections. Author's analysis, page dated 17 April 2015.
4. [Esolangs, Malbolge](https://esolangs.org/wiki/Malbolge). Community article; source review on 2026-10-27. Do not use its historical assertions as a substitute for original evidence.
5. Project source: [`malbolge/core.py`](../../malbolge/core.py), [`malbolge/malbolge.py`](../../malbolge/malbolge.py), [`malbolge/__init__.py`](../../malbolge/__init__.py), and [`AGENTS.md`](../../AGENTS.md). Implementation review on 2026-10-27.
