# Debugger UI architecture: one ViewModel, two renderers

> **English** | [中文](tui-web-architecture.zh.md)
>
> Written 2026-08-28. Decides the structure for rebuilding the debugger UI
> against the imported design canvas (`tui-redesign/`) while keeping a browser
> build reachable from the same core. Status: **design, partly implemented** —
> nothing under `malbolge/view/` or `malbolge/tui/` exists yet. Roadmap entry:
> `docs/research/roadmap.md` P4 "Debugger UI rebuild".

---

## 1. The problem this solves

`malbolge/debug_tui.py` is 787 lines in a single file. Every panel holds the
`MalbolgeDebugger` directly, calls `get_state()` for itself (7 calls per
refresh, 11 once the redesign lands), and three of them reach past the public
API into `debugger._mem` and `debugger._input_pos`. Every panel renders by
hand-assembling a Rich markup string, which forces manual `[` escaping —
already one `escape_markup` helper plus three scattered `.replace('[', '\\[')`
calls.

That is survivable for one renderer. It is not survivable for two.

The decision is therefore to split the UI into three layers and put the
platform boundary at a **data** interface, not a widget interface:

```
malbolge/core.py · malbolge.py · malbolge20.py     engine
malbolge/debugger.py                               debug control
        │                                          (breakpoints, history, preview)
        ▼
malbolge/view/                     ★ ViewModel — pure Python, JSON-only
        │
        ├──▶ malbolge/tui/         Textual renderer  (canvas 1a / 1b / 1c)
        └──▶ web/                  Pyodide + real web controls (canvas pending)
```

What the two renderers share is **meaning** ("this cell has been written 3
times", "this row is the current instruction", "this breakpoint has been hit
3 times"). What they do not share is **presentation** — a terminal and a
browser have incompatible layout capabilities, and forcing one presentation
layer onto both makes both worse.

## 2. The two rules of `malbolge/view/`

These are not style preferences. Both are enforced by the runtime.

**Rule 1 — no `import textual`, anywhere under `view/`.** The web build runs
this layer inside Pyodide, where Textual is neither present nor meaningful.

**Rule 2 — every ViewModel return value must survive `json.dumps()`.** The
web build runs Pyodide inside a Web Worker (see §5), and Worker traffic goes
through `postMessage`, i.e. structured clone. An accidental Rich `Segment`,
`Enum`, or callable in a return value breaks the web build at runtime rather
than at review time.

Rule 2 has an immediate concrete consequence: `Breakpoint.condition` is a
`Callable`, so `BreakpointView` exposes `has_condition: bool`, never the
predicate itself. `StopReason` is an `Enum`, so views emit `stop_reason.value`
(a `str`). A `test_view_json.py` asserting `json.dumps(view)` on every
ViewModel is the cheapest possible guard and is part of the deliverable.

Not a rule, but a consequence worth stating: because ViewModels are plain
data, they are tested with ordinary pytest — no Textual pilot, no terminal.
This is the layer that parallelizes best and verifies most cheaply.

## 3. ViewModel contracts

Six ViewModels, one per panel family. Field names below are normative — the
TUI and the web build are both written against them.

### 3.1 `RegisterView`

```python
{
  "a": int, "a_char": str,          # a_char: printable or "."
  "c": int, "d": int,
  "next_a": int | None,             # from preview_next_instruction()
  "next_c": int | None,
  "next_d": int | None,
  "step": int,
  "history_size": int,
  "output_len": int,
  "input_consumed": int,
  "input_total": int,
  "terminated": bool,
  "stop_reason": str,               # StopReason.value
}
```

### 3.2 `DisasmView`

```python
{
  "center": int,                    # C at snapshot time
  "window": [int, int],             # inclusive address range shown
  "rows": [
    {
      "addr": int,
      "raw": int,                   # mem[addr]
      "char": str,
      "legal": bool,                # 33 <= raw <= 126
      "opcode": int | None,         # None when not legal
      "mnemonic": str,              # "???" for unknown opcodes
      "effect": str,                # NEW: "d ← mem[d]", "c ← mem[d]", …
      "is_current": bool,
      "has_breakpoint": bool,
    }
  ],
}
```

`effect` is new, and it is a **semantic key, not display text** — one of
`disasm.EFFECT_KEYS`: the eight executable mnemonics (`jmp` `out` `in` `rotr`
`mov` `crz` `nop` `end`) plus `unknown_opcode` and `illegal`. Each renderer
maps the key to its own wording.

It shipped briefly as an English display string ("d ← mem[d]"), which was
wrong for the reason this whole layer exists: the web canvas is in Chinese, so
baking one natural language into the shared layer leaves the other renderer
either wrong or reverse-engineering text back into meaning.

The two non-executing keys are deliberately distinct, because they are
different sentences: at an `illegal` cell (outside 33..126) the machine
*stops*; an `unknown_opcode` (printable, but `(raw + addr) % 94` is none of
the eight) is *skipped* and execution carries on. `legal` plus
`mnemonic == "???"` can already distinguish them, but only if every renderer
independently knows that rule — naming them here makes a renderer's lookup
table total over `EFFECT_KEYS` with no second field to consult.

### 3.3 `MemoryView`

```python
{
  "d": int, "c": int,
  "start": int, "count": int,
  "offset": int,                    # manual scroll offset relative to D
  "heat_max": int,                  # max heat within this window, for normalising
  "cells": [
    {
      "addr": int, "value": int, "char": str,
      "heat": int,                  # cumulative write count, see §4.1
      "is_d": bool, "is_c": bool,
      "just_written": bool,         # written by the step that produced this snapshot
    }
  ],
}
```

`heat_max` is per-window, not global: the heat map normalises against what is
on screen, otherwise one very hot cell flattens everything else to black.

The window is **centred** on `d + offset` — `start = d + offset - count // 2`,
clamped into the address space — which is the rule the single-file TUI used
(`start_addr = center - half_cells`). Centring lives here, not in the
renderers: a window anchored *at* D shows only never-executed addresses ahead
of the data pointer, which hides exactly the recently-written cells the heat
map exists to show. (Recorded because the first implementation read the
under-specified original literally and anchored at D — every heat value in the
window came back 0.)

### 3.4 `TeachingView`

Feeds canvas 1b and the engineering-mode teaching panel from the same data.

```python
{
  "terminated": bool,
  "will_terminate": bool,
  "opcode": int, "opcode_name": str,
  "syntax": str, "description": str,           # from OPCODE_HELP
  "opcode_calc": {"mem_c": int, "mem_c_char": str, "c": int, "opcode": int},
  "effects": [                                 # canvas 1b's "4 things happen"
    {"order": int,
     "kind": "register" | "memory" | "encrypt" | "io" | "note",
     "text": str,
     "detail": str | None}
  ],
  "encrypt": {"addr": int, "index": int,
              "old": int, "old_char": str,
              "new": int, "new_char": str} | None,
  "ternary": {"kind": "crazy" | "rotate",
              "a": [int], "b": [int] | None, "result": [int],
              "highlight_before": int, "highlight_after": int} | None,
}
```

The `effects` list is the ordered, enumerated form canvas 1b renders as
numbered badges; the engineering mode renders the same list as compact lines.
Ordering is defined by the ViewModel, not by either renderer.

### 3.5 `TimelineView`

```python
{
  "current": int,
  "max_reached": int,
  "seekable": [int, int],           # inclusive; bounded by the history window, §4.3
  "marks": [{"addr": int, "kind": "breakpoint" | "watchpoint"}],
}
```

### 3.6 `BreakpointView`

```python
{
  "breakpoints": [
    {"addr": int, "mnemonic": str, "hit_count": int,
     "enabled": bool, "temporary": bool, "has_condition": bool}
  ],
  "watchpoints": [
    {"addr": int, "enabled": bool, "last_value": int | None}
  ],
}
```

`Watchpoint` has no `hit_count` today; canvas 1a does not show one either, so
none is added.

### 3.7 The snapshot

All six are built once per state change from a single `DebuggerSnapshot`, not
independently on demand. This is what prevents a torn frame during timeline
scrubbing, where a rebuild is triggered every drag event and an
each-panel-asks-for-itself model would show disassembly at step 900 while
memory is still at step 380.

```python
def build_snapshot(dbg, *, mem_offset=0, mem_count=24, disasm_count=11) -> dict:
    """Returns {"registers": …, "disasm": …, "memory": …,
                "teaching": …, "timeline": …, "breakpoints": …}"""
```

## 4. Backend additions (`debugger.py`)

Three, all in `debugger.py`, all covered by `test_debugger.py`.

### 4.1 Memory write heat

```python
@property
def write_heat(self) -> Mapping[int, int]: ...
def get_write_heat(self, start: int, count: int) -> list[int]: ...
```

Counts every assignment to `mem[addr]` — including the per-step ENCRYPT
rewrite, and the writeback of `crz` / `rotr`. `_save_history` already collects
a `mem_changes` dict per step, so the counter is a small accumulator beside
it. `get_write_heat` returns 0 for never-written addresses rather than
raising.

Reset semantics: `reset()` clears heat. `step_back()` **decrements**, so that
heat stays consistent with the reachable timeline rather than counting undone
work.

### 4.2 Interruptible chunked run

```python
def run_chunked(self, chunk: int = 5000) -> Iterator[MalbolgeState]:
    """Yield the current state every `chunk` steps. The caller may stop
    iterating at any time; stopping does not corrupt debugger state."""
```

This is required by Pyodide — the web build is single-threaded per worker and
a synchronous hundred-thousand-step `run()` freezes the page, stop button
included. **It is equally a TUI fix**: `action_run` currently calls
`run(max_steps=100000)` and the terminal UI is frozen for the duration, which
nobody has complained about only because terminals hide it well.

`run(max_steps=…)` keeps its exact current signature and behaviour, and is
reimplemented on top of `run_chunked`.

### 4.3 Timeline seek

```python
@property
def max_step_reached(self) -> int: ...
@property
def seekable_range(self) -> tuple[int, int]: ...
def seek(self, step: int) -> MalbolgeState: ...
```

`seek` walks backwards with `step_back` when the target is inside the history
window, and forwards with `step` otherwise. `ValueError` when
`step > max_step_reached`.

**The window is real and the design canvas ignores it.** `debugger.py:271`
pins `_max_history = 10000` and `_save_history` drops the oldest entry beyond
that, while canvas 1a's timeline reads `380 / 1.2M`. Decision: **window-style
(option A)** — the timeline draws the full extent but only `seekable_range` is
draggable, the rest rendered inert. Honest, and costs nothing.

The alternative (periodic full-memory checkpoints, replay from the nearest
one) is deferred as its own investigation: its cost is dominated by how
expensive a Malbolge20 `SparseMemory` snapshot is, which is an unmeasured
number and must not block this work.

## 5. Renderers

### 5.1 TUI — `malbolge/tui/`

```
malbolge/tui/
  __init__.py      re-exports run_tui, main, DebuggerApp
  app.py           engineering-mode Screen (canvas 1a)
  theme.py         semantic colour tokens + CSS
  screens/
    help.py        HelpScreen (moved verbatim)
    teaching.py    teaching-mode Screen (canvas 1b)
  panels/
    base.py        shared markup escaping
    registers.py  disasm.py  memory.py  io.py  status.py
    breakpoints.py  timeline.py  command.py  source.py     (new)
```

`malbolge/debug_tui.py` shrinks to a six-line shim re-exporting `run_tui`,
`main` and `DebuggerApp`. It is **not** deleted: `malbolge/__main__.py:90` and
`malbolge/debug_cli.py:587` import from it, and the name appears in CLAUDE.md
and the README. Breaking that path buys nothing.

Decisions taken, with the reasoning kept because these will be re-litigated:

| Question | Decision | Why |
|---|---|---|
| Refresh granularity | Tiered: full refresh on ordinary actions, light-panels-only while scrubbing or running. Structure leaves room for reactive dependency sets, but does not build them | Full-refresh-everything visibly stutters once scrubbing exists; a complete reactive dependency map across 11 panels is real work with no measurement yet to justify it |
| Rendering | Mixed: text panels keep Rich markup; graphical panels (heat map, timeline, ternary grid) implement `render()` returning a Rich renderable | String-assembling a 96-cell coloured grid is both unreadable and untestable, and sidesteps `[`-escaping entirely |
| 1a vs 1b | Two separate `Screen`s, `Tab` to switch | Their panel sets barely overlap; one Screen would be a `compose()` full of conditionals. Shared state is the snapshot, not the Screen |
| 1c (80×24) | **Not** a responsive-CSS problem | Collapsing three columns into `1`–`5` tabs is an information-architecture change, not a layout tweak. Needs a `TabbedContent` that expands to columns when wide. Hardest single piece; gets its own phase |
| Colour | `theme.py` exposes semantic tokens only (`CURRENT`, `BREAKPOINT`, `WATCHPOINT`, `WRITTEN`, `DIM`, `ACCENT`); panels never write literal colours | Today's four border colours (`$primary/$secondary/$accent/$success`) carry no semantics. Three canvases share one palette; spread across 11 files it will drift. Also makes "a light theme too" a one-file change |

The source panel (canvas 1a, left column, `PYTHON` / `.mal` / `.mg` tabs) ships
as a **placeholder marked "not wired"**: the compiler emits no line mapping or
debug metadata, so py→mg→mb provenance does not exist to display. Building it
belongs with the IR work in `mb-dialect-plan.md`, not here.

### 5.2 Web — `web/` (design canvas pending)

Form: **Pyodide, fully static**, no server. The package is pure Python with no
C extensions, so it loads into Pyodide as-is and hosts from GitHub Pages.

Structure, not yet built:

- Pyodide runs in a **Web Worker**; the main thread only renders. This is what
  makes Rule 2 load-bearing.
- The worker exposes exactly the §3 snapshot plus the command surface
  (step / back / run / seek / breakpoint / watchpoint).
- **v1 supports original Malbolge only** (59,049 cells). Malbolge20's 3.48
  billion-cell sparse memory needs its browser-heap behaviour measured before
  being promised.

Deliberately open until a design canvas exists: the visual language. The
`tui-redesign/` canvas is terminal-shaped — monospace, dark, 80×24 constraints,
character-block heat maps. Transplanting that to a browser produces a fake
terminal on a web page, which would be strictly worse than just serving the
real TUI over `textual-web`. A genuine web build needs its own canvas, and the
implementation waits for it.

## 6. Phasing and parallel boundaries

Ordering constraint: `debug_tui.py` has **zero test coverage** today
(`test_debugger.py` covers the backend only). Splitting a 787-line file across
several agents without a regression net, and then changing behaviour in the
same pass, is how silent breakage gets in.

| Phase | Work | Parallel? |
|---|---|---|
| 0a | Split `debug_tui.py` into `malbolge/tui/`, behaviour byte-identical, shim left behind | serial |
| 0b | `test/test_debug_tui.py` — Textual `App.run_test()` pilot smoke tests pinning current keybinding behaviour | parallel with 0a (new file, and 0a preserves import paths) |
| 1 | Backend §4 · `view/` ViewModels §3 · disasm panel · new panels (breakpoints / timeline / command) · teaching Screen | yes — disjoint files |
| 2 | Memory heat map (needs §4.1) · layout, theme, 1c tabs | serial after 1 |
| 3 | Web build | blocked on its design canvas |

`view/` is the best parallelisation target in the whole project: pure data,
plain pytest, no terminal, and a contract fixed in §3 before anyone starts.

## 7. Open questions

1. **`view/` granularity.** Six ViewModels, one per panel family (as specced),
   or three by data domain (execution state / memory / metadata)? Six matches
   the canvas and keeps agent boundaries clean; three has less duplication in
   the snapshot builder. Currently: six.
2. **Checkpointed timeline** (§4.3) — needs a Malbolge20 `SparseMemory`
   snapshot cost measurement before it can even be scoped.
3. **Web visual language** — blocked on a design canvas.
4. **`textual-web` as a byproduct.** Nearly free once the TUI is rebuilt, and
   a reasonable stopgap while the web canvas does not exist. Not scheduled.
