# TUI redesign canvas (imported from Claude Design)

> **English** | [中文](README.zh.md)
>
> Imported 2026-08-28 from the Claude Design project **"Pymalbolge TUI 重设计"**
> (`727e8ee9-4482-4efe-9ff7-2e373ceeec61`). Design draft, **not implemented** —
> nothing in `malbolge/debug_tui.py` has been changed to match it.

## Files

| File | What it is |
|---|---|
| `Malbolge TUI.dc.html` | The canvas source, byte-for-byte as stored in the Claude Design project. Four artboards on one pan/zoom canvas. Needs `support.js` (the dc-runtime) to render with its interactive props |
| `preview.html` | Derived, offline-viewable copy: `support.js` dropped, the one template variable (`scanBg`, the scanline toggle) resolved to `none`. Open it in any browser — no network, no runtime |
| `support.js` | The dc-runtime bundle the canvas loads. Generated artifact of Claude Design (`dc-runtime/src/*.ts`), not our code, not hand-editable |
| `github.md` | The design project's own record of which source files each artboard was derived from |

## Artboards

| ID | Direction | Terminal size |
|---|---|---|
| `0a` | Baseline: 1:1 reproduction of today's Textual TUI (2×4 grid, four border colours, status bar) | — |
| `1a` | **Maximum information density** (engineering-facing): source/`.mal`/`.mg` tabs with py→mg→mb mapping, call-structure tree, breakpoint & watchpoint list, disassembly with effect column, memory write-heat map, ternary `rotr` preview, scrubable timeline, `:` command line | 150×42 |
| `1b` | **Teaching-facing**: current instruction at 44px, the `(mem[C] + C) % 94` derivation spelled out, the four things one step does enumerated, the ENCRYPT table shown rewriting the cell just executed | — |
| `1c` | `1a` collapsed for an 80×24 terminal: panels become `1`–`5` tabs, heat map shrinks to one strip | 80×24 |

The canvas's own critique of `0a`: the four border colours carry no semantics,
memory shows only 24 cells, the register panel is ~60% whitespace, and there is
no breakpoint / source / timeline view at all.

## Editing

The canvas is edited in its published Claude Design project, not here. Re-import
with `DesignSync get_file` after changes there; this directory is a snapshot,
not a sync target.
