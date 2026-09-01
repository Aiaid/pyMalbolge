/**
 * Design tokens for the web debugger, ported verbatim from the canvas.
 *
 * Source: `docs/design/web-ui-canvas/Malbolge Web.dc.html`, the `T` object in
 * `renderVals()` (screen 3a carries both branches) plus `opC` / `inkOp`,
 * `fxMap`, `_heat()` and the two legend gradients. Every literal here is a
 * copy, not a re-derivation -- if a value looks like it wants rounding to a
 * 4px grid, that is the canvas's choice and it stays.
 *
 * The light set is complete rather than stubbed: the canvas already specifies
 * it in full, so "the light theme is a later swap rather than a later rewrite"
 * (`docs/design/tui-web-architecture.md` §5.2 v1 scope) only needs the screens
 * to read tokens instead of literals. Screen 1a currently mounts dark.
 */

/* ------------------------------------------------------------------ tokens */

/** Dark tokens -- the `dark` branch of the canvas's `T`. */
export const DARK = {
  name: "dark",
  pg: "#0d0c12", bd: "#2a2735", bar: "#100e16", barBd: "#232030",
  pn: "#14121a", pnBd: "#262331", hd: "#221f2d",
  in1: "#17151f", in1Bd: "#2e2a3c", in2Bd: "#221f2d",
  tx: "#e9e6f2", sub: "#cfc9e0", mut: "#8b8798", faint: "#7d7890",
  dim: "#6f6a80", ghost: "#4d4860",
  acc: "#ff5c38", accTx: "#160a08", accSoft: "#ffb49e",
  amb: "#ffb454", cyn: "#7fe3ef", grn: "#8fd12f",
  headFont: "'Space Grotesk','Noto Sans SC',sans-serif",
  monoFont: "'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace",
  logo2: "#5a5470",
  hatch: "repeating-linear-gradient(-45deg,#1b1824 0 6px,#15131d 6px 12px)",
  tlBd: "#2e2a3c", tlBg: "#17151f", tick: "#221f2d", mark: "#4d4860",
  outBg: "#0d0c12", outBd: "#221f2d", outTx: "#e9e6f2",
  cur: "#ff5c38", knobIn: "#160a08",
  dChip: "color-mix(in oklab,#4fd8e8 14%,transparent)",
  dChipBd: "#2a4a52", dChipTx: "#7fe3ef",
  tglDBg: "#2e2a3c", tglDTx: "#e9e6f2", tglLBg: "transparent", tglLTx: "#8b8798",
  // Not in `T`: values screen 1a inlines outside the 3a token pass.
  dRing: "#4fd8e8",          // memory D-pointer ring (canvas `_cells`)
  wRing: "#ffd166",          // memory just-written ring (canvas legend)
  hoverRing: "#cfc9e0",      // memory hover ring (canvas `_cells`)
  tipBg: "#1c1926", tipBd: "#3a3450",
  tipShadow: "0 12px 32px rgba(0,0,0,.55)",
  // Launch screen (canvas 1d). `err` shares its hex with OP_COLORS.dark.end
  // by coincidence -- an error banner and the `end` mnemonic are unrelated,
  // so do not collapse them.
  dropBg: "#12101a", cardHoverBg: "#171422",
  tagline: "#a79fc0", err: "#ff8c7a",
};

/** Light tokens -- the `!dark` branch of the canvas's `T` (screen 2a's paper). */
export const LIGHT = {
  name: "light",
  pg: "#f5f2ea", bd: "#d8d1c0", bar: "#fdfcf8", barBd: "#d8d1c0",
  pn: "#fdfcf8", pnBd: "#ddd6c6", hd: "#eae4d5",
  in1: "#f7f4ec", in1Bd: "#c9c1ae", in2Bd: "#e5dfd0",
  tx: "#2a2622", sub: "#5a5348", mut: "#8a8272", faint: "#a89e8a",
  dim: "#a89e8a", ghost: "#c2bba9",
  acc: "#b03a26", accTx: "#fdf6ee", accSoft: "#b03a26",
  amb: "#c07a1e", cyn: "#1e7f8c", grn: "#4a7c2f",
  headFont: "'Spectral','Noto Serif SC',serif",
  monoFont: "'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace",
  logo2: "#c9c1ae",
  hatch: "repeating-linear-gradient(-45deg,#e8e1d1 0 6px,#efe9dc 6px 12px)",
  tlBd: "#d0c8b4", tlBg: "#fdfcf8", tick: "#eae4d5", mark: "#b5ac97",
  outBg: "#2a2622", outBd: "#2a2622", outTx: "#f0ece1",
  cur: "#e8a04c", knobIn: "#fdf6ee",
  dChip: "color-mix(in oklab,#1e7f8c 10%,#fdfcf8)",
  dChipBd: "#b9d4d8", dChipTx: "#1e7f8c",
  tglDBg: "transparent", tglDTx: "#8a8272", tglLBg: "#2a2622", tglLTx: "#fdfcf8",
  dRing: "#1e7f8c", wRing: "#c07a1e", hoverRing: "#2a2622",
  tipBg: "#fdfcf8", tipBd: "#d0c8b4",
  tipShadow: "0 12px 32px rgba(42,38,34,.18)",
  // Launch screen. NOT from the canvas -- it only drew 1d in dark. These are
  // derived from the tokens above (dropBg/cardHoverBg one step down from `pn`,
  // tagline = `mut`, err a deeper red than `acc` so it reads as a warning and
  // not as the accent). Replace with real values when a light 1d is drawn.
  dropBg: "#efe9dc", cardHoverBg: "#eae4d5",
  tagline: "#8a8272", err: "#a02c1a",
};

export const THEMES = { dark: DARK, light: LIGHT };

/**
 * Mnemonic -> colour. Dark is the canvas's `opC`, light its `inkOp`.
 * `DATA` / `???` rows are deliberately absent: they fall back to a dim token.
 */
export const OP_COLORS = {
  dark: {
    crz: "#ffb454", jmp: "#b48cff", out: "#7fe3ef", in: "#7fe3ef",
    rotr: "#ffb454", mov: "#8fd12f", nop: "#7d7890", end: "#ff8c7a",
  },
  light: {
    crz: "#c07a1e", jmp: "#6a4fa3", out: "#1e7f8c", in: "#1e7f8c",
    rotr: "#c07a1e", mov: "#4a7c2f", nop: "#8a8272", end: "#b03a26",
  },
};

/* ------------------------------------------------------- semantic wordings */

/**
 * `DisasmView.rows[].effect` is a semantic key, never display text
 * (`docs/design/tui-web-architecture.md` §3.2). This is the web renderer's
 * lookup, and it is total over `disasm.EFFECT_KEYS`.
 *
 * The eight executable entries are the canvas's `fxMap` verbatim. The two
 * non-executing keys are not in the canvas's map -- it hard-coded their
 * wording inside `renderVals()` -- so they are lifted from there: a printable
 * cell with no matching opcode is skipped, an out-of-range cell stops the
 * machine, and §3.2 is explicit that those are different sentences.
 */
export const EFFECT_TEXT = {
  jmp: "c ← mem[d]",
  out: "输出 chr(a%256)",
  in: "a ← 读入字符",
  rotr: "a,mem[d] ← rot(mem[d])",
  mov: "d ← mem[d]",
  crz: "a,mem[d] ← crz(a,mem[d])",
  nop: "—",
  end: "终止",
  unknown_opcode: "视作 nop",
  illegal: "不可执行 · 触碰即终止",
};

/** `RegisterView.a_char_kind` -> the A-register subtitle's tail. */
export const CHAR_KIND_TEXT = {
  printable: "可打印",
  control: "控制符",
  other: "非 ASCII",
};

/** `TeachingView.effects[].kind` -> token name used to colour its bullet. */
export const EFFECT_KIND_TOKEN = {
  register: "cyn",
  memory: "amb",
  encrypt: "acc",
  io: "grn",
  note: "mut",
};

/** `TeachingView.effects[].kind` -> the engineering-mode label (canvas 1b). */
export const EFFECT_KIND_LABEL = {
  register: "寄存器",
  memory: "内存",
  encrypt: "加密",
  io: "输入输出",
  note: "说明",
};

/** `RegisterView.stop_reason` -> status pill wording. */
export const STOP_REASON_TEXT = {
  running: "运行中",
  step: "已暂停",
  breakpoint: "断点",
  watchpoint: "监视点",
  terminated: "已终止",
  error: "错误",
  input_exhausted: "输入耗尽",
};

/* ------------------------------------------------------------- heat colour */

/** Heat ramps, verbatim from `_heat()`. Stops are `[t, hex]`, t in 0..1. */
export const HEAT_PALETTES = {
  blackbody: [[0, "#16141c"], [0.28, "#37152a"], [0.55, "#8c2620"],
              [0.8, "#ea5b22"], [1, "#ffc668"]],
  toxic: [[0, "#141a16"], [0.3, "#123527"], [0.6, "#2c6e33"],
          [0.85, "#7fbf2e"], [1, "#eaff70"]],
  paper: [[0, "#efe9dc"], [0.3, "#eed9a8"], [0.6, "#dd9a4e"],
          [0.82, "#c05a2a"], [1, "#8c2620"]],
};

/** Legend gradients, verbatim from `legendGrad` / `legendGradL`. */
export const HEAT_GRADIENTS = {
  blackbody: "linear-gradient(90deg,#16141c,#37152a,#8c2620,#ea5b22,#ffc668)",
  toxic: "linear-gradient(90deg,#141a16,#123527,#2c6e33,#7fbf2e,#eaff70)",
  paper: "linear-gradient(90deg,#efe9dc,#eed9a8,#dd9a4e,#c05a2a,#8c2620)",
};

/** Component-wise hex lerp -- the canvas's `_lerpHex`. */
export function lerpHex(h1, h2, t) {
  const parse = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const a = parse(h1), b = parse(h2);
  return "#" + a
    .map((v, i) => Math.round(v + (b[i] - v) * t).toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Sample a heat ramp at `t` (0..1) -- the canvas's `_heat()`, generalised over
 * the palette name instead of the `light` boolean plus a `heat` prop.
 */
export function heatColor(t, palette = "blackbody") {
  const pal = HEAT_PALETTES[palette] || HEAT_PALETTES.blackbody;
  const x = Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0));
  for (let i = 1; i < pal.length; i++) {
    if (x <= pal[i][0]) {
      const [t0, c0] = pal[i - 1], [t1, c1] = pal[i];
      return lerpHex(c0, c1, t1 === t0 ? 0 : (x - t0) / (t1 - t0));
    }
  }
  return pal[pal.length - 1][1];
}

/**
 * Normalise a raw write count into the 0..1 the ramp expects.
 *
 * `MemoryView.heat_max` is per-window, and on real programs the window is
 * violently skewed: at step 21,500 of `truth.mal` one cell has been written
 * 5,883 times and the next-hottest 3, so dividing by `heat_max` paints 287 of
 * 288 cells the palette's t=0 black and tells the reader nothing. `log` is
 * therefore the default and `linear` -- the literal reading of the contract --
 * stays available; the legend says which one is on, because the two produce
 * genuinely different pictures and the reader has to know which they are
 * looking at.
 */
export function heatT(heat, heatMax, scale = "log") {
  if (!heatMax || heat <= 0) return 0;
  if (scale === "linear") return Math.min(1, heat / heatMax);
  return Math.min(1, Math.log1p(heat) / Math.log1p(heatMax));
}

/* ------------------------------------------------------------ CSS plumbing */

/**
 * Write a token set onto an element as `--mb-*` custom properties, so the
 * stylesheet can be authored once and re-pointed by swapping themes.
 */
export function applyTheme(el, theme = "dark") {
  const t = typeof theme === "string" ? (THEMES[theme] || DARK) : theme;
  for (const [k, v] of Object.entries(t)) {
    if (typeof v === "string") el.style.setProperty(`--mb-${k}`, v);
  }
  el.dataset.mbTheme = t.name;
  return t;
}

/** The mnemonic palette for a theme name, for renderers that colour opcodes. */
export function opColors(themeName = "dark") {
  return OP_COLORS[themeName] || OP_COLORS.dark;
}
