# HeLL Language Specification (Reverse-Engineered from LMAO v0.6.0)

> [中文](hell-spec.zh.md) | **English**

> This document was compiled by cross-checking `ref/LMAO/src/lmao.l`, `lmao.y`, `label.c`, `prefix.c`, `xlat.c`,
> `layout.c`, `initialize.c`, `malbolge.h/.c`, and the LMAO README line by line,
> and by comparing it point-by-point against the six examples under `test/fixtures/hell/`.
> It serves as the implementation reference for pyMalbolge's Python HeLL assembler.
> Compiled: 2026-07-20; LMAO version: v0.6.0 (commit 3ea747e).

---

## I. Lexical Analysis (from `lmao.l`)

### 1.1 Whitespace and Comments

- Whitespace: `[ \t\r]`, plus a bare newline `\n`; both clear the internal `require_whitespace` flag (see 1.4).
- Comments (discarded entirely, produce no token):
  - Line comments: start with `;`, `%`, `#`, or `//` and run to end of line;
  - Block comments: `/*...*/`; a lone `*` or `/` may appear inside, as long as it is not immediately followed by `*/` it does not end early.

### 1.2 Block Separation (Three Sources of EMPTYLINE)

- **Blank line**: "newline — optional whitespace — another newline". Consecutive blank lines produce only a single `EMPTYLINE`, and only when **not inside braces**; blank lines inside braces are silently discarded.
- **`{`**: sets the suppress flag and returns `EMPTYLINE`; encountering another `{` while braces are already open is an error.
- **`}`**: clears the suppress flag and returns `EMPTYLINE`; an error if there is no matching `{`.
- **Key fact**: `{`, `}`, and blank lines all reduce to the **same EMPTYLINE token** at the grammar level — braces are just an "explicit spelling" of a blank line. A `}{` sequence closes the previous block and immediately opens the next one (equivalent to a blank line in between).
- It is a fatal error if braces are still open (unclosed) at end of file.

### 1.3 Section Headers `.CODE` / `.DATA`

- Section headers MUST NOT appear inside a `{ }` block (error).
- `.DATA` sets the `in_data_section` flag; `.CODE` clears it. This flag determines the lexical role of `/` (see 1.7).

### 1.4 Identifier-class Tokens and the "Separator Required" Rule

- `identifier = [A-Za-z_][0-9A-Za-z_]{0,99}` (100 characters max); `label = identifier ':'`.
- `U_{identifier}` → a U_-prefixed token (value is the name with the prefix stripped); `R_{identifier}` likewise.
- **Malbolge command keywords, `U_...`, and `R_...` MUST NOT be used as label names** (a lexical-level error). However, `U_x` and `R_x` as plain identifiers (not label definitions) are allowed, dedicated to prefix references inside `.DATA` expressions.
- **The `require_whitespace` mechanism**: after a "word-like" token — string, character literal, numeric constant, `C0/C1/C2/C20/C21/EOF`, `RNop`, command mnemonic, prefixed identifier, or plain identifier — matches successfully, the flag is set; if the next token is also a "word-like" token, it is an error ("Misformed identifier"). That is, **forms like `42abc`, `'a'C1`, `InOut` written back-to-back are illegal** and must be separated by whitespace or punctuation. Comma, braces, operators, whitespace, and newline clear this flag; `(` and `)` do not.

### 1.5 Numeric Literals

| Syntax | Value | Notes |
|---|---|---|
| `0*[0-9]{1,5}` | Decimal, leading zeros allowed | > 59048 is an error ("Integer too big") |
| `0t[0-2]{1,10}` | Ternary, most significant digit first | Up to 10 digits, naturally ≤ 59048; not actually used in the six examples |
| `'c'` | Single-character ASCII value | A bare character excludes `'` and `\`; the only escapes are `\' \n \r \t \\` (**no `\0`** — `'\0'` yields the value of the character `'0'`) |
| `C0/C1/C2/C20/C21/EOF` | 0 / 29524 / 59048 / 59046 / 59047 / 59048 | `EOF` is a synonym for `C2` |

### 1.6 String Literals

Enclosed in double quotes, backslash escapes allowed; bare newlines and unescaped quotes are not allowed. Escape decoding happens at the grammar-action layer (see 3.2), supporting `\n \r \t \\ \0` (**strings DO support `\0`**, unlike character literals).

### 1.7 Special Symbols

| Symbol | Meaning |
|---|---|
| `,` | Used only in `STRING , Dataexpression` (separator between string characters) |
| `{` `}` | Both produce EMPTYLINE (see 1.2) |
| `.OFFSET` / `@` | Equivalent; `@` does not require a separating whitespace |
| `?` | DONTCARE: occupies an address but its value is not guaranteed |
| `?-` | NOTUSED: occupies no address at all |
| `+ - * / >> << !` | Operators; **`/` is context-dependent**: division in the `.DATA` section, xlat2 cycle separator in the `.CODE` section |
| `( )` | Grouping |

Any other character → lexical error.

---

## II. Grammar (Approximate EBNF, based on `lmao.y`)

```ebnf
Start            ::= EMPTYLINE* Program
Program          ::= ( Code | Data )*
Code             ::= ".CODE" Codeblocks
Data             ::= ".DATA" Datablocks

Codeblocks       ::= Codeblock ( EMPTYLINE Codeblock )*
Datablocks       ::= Datablock ( EMPTYLINE Datablock )*

Offset           ::= ( ".OFFSET" | "@" ) CONSTANT EMPTYLINE*

Codeblock        ::= ε | Offset? LABEL Codeexpressions
Datablock        ::= ε | Offset? LABEL Dataexpressions

Codeexpressions  ::= ( LABEL | Codeexpression )*
Codeexpression   ::= "RNop" | XlatCycle
XlatCycle        ::= COMMAND ( "/" COMMAND )*
                     /* COMMAND ∈ {MovD,Nop,Jmp,In,Out,Opr,Rot,Hlt} */

Dataexpressions  ::= ( LABEL | Dataexpression
                     | STRING | STRING "," Dataexpression )*

Dataexpression   ::= Dataexpression (">>"|"<<") Crazied   /* left-associative, lowest precedence */
                    | Crazied | "?" | "?-"
Crazied          ::= Crazied "!" Sum | Sum                 /* left-associative */
Sum              ::= Sum ("+"|"-") Product | Product       /* left-associative */
Product          ::= Product ("*"|"/") Dataatom
                    | Product ("*"|"/") "(" Dataexpression ")"
                    | Dataatom | "(" Dataexpression ")"
Dataatom         ::= CONSTANT | IDENTIFIER
                    | R_PREFIXED_IDENTIFIER
                    | U_PREFIXED_IDENTIFIER IDENTIFIER     /* U_TARGET ANCHOR */
```

**Operator precedence** (low to high, counter to common intuition): `>> <<` < `!` < `+ -` < `* /`.

**Each Dataexpression / Codeexpression (as well as each character produced by string expansion) corresponds to exactly one consecutive memory cell** — the whitespace-separated expressions within a block are filled into adjacent addresses in order.

**Multiple labels can share the same cell** (label aliasing): a `LABEL` may appear repeatedly within an expression sequence.

**An empty block reduces to nothing and is discarded**, so a `}{` sequence is legal.

---

## III. Semantics

### 3.1 `.CODE` Section: xlat2 Cycles and the 8 Commands

| Mnemonic | Opcode | Semantics |
|---|---|---|
| Nop | 68 | No-op (every value that does not fall on one of the other 7 opcodes is Nop) |
| MovD | 40 | `D = [D]`; C and D increment |
| Opr | 62 | `A,[D] = crazy(A,[D])`; C and D increment |
| Jmp | 4 | `C = [D]`; only D increments |
| Rot | 39 | `A,[D] = rotate_right([D])`; C and D increment |
| Out | 5 | Output `A mod 256`; C and D increment |
| In | 23 | Read one character into A; on EOF, `A = C2`; C and D increment |
| Hlt | 81 | Halt |

- **Single command** (e.g. `Jmp`): only the first execution is guaranteed to be that opcode; the self-modified result after execution is unconstrained and may be placed at any legal address.
- **xlat2 cycle `Cmd1/.../CmdN`**: the sequence of opcodes the cell exhibits over N consecutive executions, cycling back to the start. Validity is checked statically (`xlat.c: is_xlatcycle_existent`): for a candidate starting character, the XLAT2 table is repeatedly applied; non-Nop opcodes must match exactly, Nop positions only need to "be Nop". Some cycle combinations are mathematically impossible → error.
- **`RNop`**: syntactic sugar for a self-looping Nop. For every address mod 94, at least one character exists that is "always Nop" (the `xlat.c`-hardcoded 94-character `immutable_nops` table), so `RNop` can be placed at any address.
- **Placement constraint**: the starting character MUST be printable ASCII (33–126) and satisfy `(address mod 94 + character value) mod 94` ∈ the set of 8 opcodes. Solved by the layout phase.

### 3.2 `.DATA` Section: Expression Evaluation (`initialize.c`)

- Arithmetic is performed **mod 59049**; negative values (from subtraction) wrap around to non-negative. Note the C source reduces overflow with `%= C2` (59048) rather than `%= 59049` — this fires only for `+`/`*` — so a port must reproduce this boundary behavior line-for-line.
- **`/` is integer division**; division by zero is unchecked (UB) in LMAO — a Python implementation SHOULD raise an explicit error.
- **`>> <<` are ternary rotations** (not shifts): `>> n` = rotate right by n digits, `<< n` = rotate right by `10-n` digits, composed from single-step `rotate_right`. **For n ≥ 10, the value is taken mod plus a warning is issued, not an error** (the README states 0≤n<10; source behavior takes precedence).
- **`!` is the crazy operation** (the same table as `crazy()` in `malbolge/core.py`).
- **Label reference evaluation**:
  - Plain `LABEL`: the target address is adjusted by "subtract 1, wrap 0 to C2" (to match the semantics of C incrementing after Jmp / D incrementing after MovD).
  - `R_LABEL`: the net effect is the target address itself (no subtraction). Constraint: the target MUST be a `.CODE` label, and MUST NOT be the last cell of its code block.
  - `U_TARGET ANCHOR`: within the **same contiguous data block**, search forward from the current cell for `ANCHOR` (a DATA label) to obtain a negative offset; `TARGET` (a CODE label) MUST be preceded by an equal-length chain of Nop cells — existing cells must all be Nop, and if `TARGET` is at the start of the block, RNop is auto-synthesized to fill the gap; otherwise it is an error.
- **`?`**: occupies an address, generates no initialization, value not guaranteed.
- **`?-`**: occupies no address; **a label MUST NOT point at `?-`** (LMAO only warns — undefined behavior; a Python implementation SHOULD raise an error directly).
- **String expansion**: `"abc"` → three cells `'a' 'b' 'c'`; `"abc", SEP` → `'a' SEP 'b' SEP 'c'` (inserted between characters, `2n-1` cells).

### 3.3 The `ENTRY` Label

The `.DATA` section MUST define an `ENTRY` label, or it is an error. At program start, D points at the `ENTRY` cell, C points at a Jmp instruction, and A's initial value is undefined. Defining `ENTRY` in the `.CODE` section has no effect (it will be treated as "entry point not found").

### 3.4 `.OFFSET` / `@`

Pins a block's first cell to an absolute address (`[0, C2]`, out-of-range is an error). A `.CODE` block reserves one extra placeholder cell immediately before the target address (`.DATA` blocks have no such reservation — the two are asymmetric). A blank line is allowed between `Offset` and the following `LABEL` (it does not split the block).

### 3.5 Invalid-Program Determination (Summary of Error Sources)

1. **Lexical level**: missing separator ("Misformed identifier"), integer out of range, illegal label name, mismatched braces, section header inside braces, unknown character.
2. **Grammar level**: LALR syntax error.
3. **Semantic level**: label redefinition; orphaned label (nothing following with a data/code word); reference to an undefined label; `R_` used at the end of a block; `U_`'s ANCHOR not in the same data block, or Nop-chain construction failure; missing `ENTRY`; xlat2 cycle not realizable; `.OFFSET` out of range or conflicting; layout unsolvable (address space cannot fit).

---

## IV. Feature-to-Example Cross-Reference Table (Six Fixtures)

| Feature | Location (file:line) |
|---|---|
| Two or more `.DATA`/`.CODE` sections | hello_world (35/136; 32/43 onward) |
| `{ }` / `}{` written back-to-back | simple_cat:38-57; cat_halt_on_eof:205/221/236/250/268 etc. |
| Line comment `;` | hello_world:214; digital_root:442-443 |
| Multiple label aliases | hello_world:312; adder:100-101 |
| All 8 mnemonics | cat_halt_on_eof, digital_root |
| 5-cycle / 9-cycle | hello_world:73; hello_world:110/114 |
| `RNop` | hello_world:111-112/126-129; cat_halt_on_eof:126-127; digital_root:197-198; adder:80-81 |
| `.OFFSET` keyword | cat_halt_on_eof:124 |
| `@` shorthand | hello_world:121; digital_root:196; adder:79 |
| Bare decimal constant | cat_halt_on_eof:434 (only occurrence) |
| `0t` ternary | not actually used |
| Character literal | simple_hello_world:67-83; digital_root:456/512 |
| String + separator | hello_world:40 (only occurrence) |
| `!` crazy | simple_hello_world:68/73 |
| `<< >>` | simple_hello_world:70/76/78/80; digital_root:456/512; adder:719/981/1075/1078 |
| `+ - *` | not used in any of the six examples (README only) |
| Parentheses | digital_root:456 |
| `U_` prefix | hello_world:147/149/151; cat_halt_on_eof:139/146/148/158/164/168-170; digital_root:211/213/247/252-253/271; adder, many places |
| `R_` prefix | used extensively across all examples (adder: 214 occurrences) |
| `?` | cat_halt_on_eof:141/150/160/167 |
| `?-` | simple_cat:48/52; hello_world:69 etc.; digital_root:510/513; adder:412/719/1061 |
| `ENTRY` | one occurrence in each of the six files |

---

## V. Notes for the Python Implementation

1. The lexical meaning of `/` switches with the current section; the lexer needs section state.
2. The `require_whitespace` separator rule MUST be implemented, or behavior will diverge from LMAO.
3. Operator precedence `>> <<` < `!` < `+ -` < `* /` is counter to intuition — do not order it by common sense.
4. `R_`/`U_` prefixes: MUST NOT be used as label names, but MAY be used as expression references — two separate rule sets apply at definition sites versus reference sites.
5. `{ }` and blank lines are handled as the same unified "block end" event.
6. Label "minus-one/wraparound", `R_` not subtracting one, and `U_`'s within-block backward ANCHOR search plus RNop-chain validation/synthesis are the most bug-prone parts — must be reproduced line-for-line against the `prefix.c`/`initialize.c` source.
7. Rotation amount out of range is "mod plus warning", not an error (per source behavior).
8. A label pointing at `?-`: LMAO only warns (undefined behavior); the Python implementation instead raises an error directly (stricter than the original).
