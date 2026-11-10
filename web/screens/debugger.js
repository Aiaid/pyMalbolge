import { tr, onLocaleChange, semanticText } from "../i18n.js";
/**
 * Canvas 1a -- the main debugger view.
 *
 * Design source: `docs/design/web-ui-canvas/Malbolge Web.dc.html`, `id="1a"`.
 * Every colour, size, radius and gap below is copied from that file rather
 * than re-derived; where a value is off a 4px grid, that is the canvas's
 * choice and it is preserved.
 *
 * Data source: `malbolge.view.build_snapshot()`, contract in
 * `docs/design/tui-web-architecture.md` §3. The canvas's `renderVals()` mock
 * data is replaced field-by-field; nothing here invents a number the snapshot
 * does not carry. Where the canvas drew something the contract cannot supply
 * -- a breakpoint's first-hit position on the time axis, the output text --
 * this file says so on screen instead of faking it.
 *
 * Update path: exactly one. Commands are fire-and-forget; every visible number
 * changes only when a `snapshot` event arrives. The single exception is the
 * `progress` event during a run, which carries a step count and nothing else,
 * and therefore updates only the step counter and the run affordances.
 */

import {
  applyTheme, opColors, heatColor, heatT, HEAT_GRADIENTS,
  EFFECT_TEXT, CHAR_KIND_TEXT, EFFECT_KIND_TOKEN, STOP_REASON_TEXT,
} from "../theme.js";

/** Heat-map geometry. 24 x 12 = 288 cells; ask for exactly that many. */
export const MEM_COLS = 24;
export const MEM_ROWS = 12;
export const MEM_COUNT = MEM_COLS * MEM_ROWS;
/** The canvas's disassembly listing is 16 rows (addresses 00030..00045). */
export const DISASM_COUNT = 16;

/** Run chunk sizes the ⏩ control cycles through (worker protocol §5.2). */
const CHUNKS = [1000, 5000, 20000];

/* ------------------------------------------------------------- formatting */

const fmt = (n) => (Number.isFinite(n) ? n.toLocaleString("en-US") : "—");
const pad5 = (n) => String(n).padStart(5, "0");

/** Rows whose `effect` says they will not execute as one of the eight ops. */
const NON_EXEC = new Set(["unknown_opcode", "illegal"]);

/* ---------------------------------------------------------- DOM utilities */

function createElement(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k === "style" && typeof v === "object") Object.assign(n.style, v);
    else if (k.startsWith("on") && typeof v === "function") {
      n.addEventListener(k.slice(2).toLowerCase(), v);
    } else n.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    n.appendChild(typeof kid === "string" ? document.createTextNode(kid) : kid);
  }
  return n;
}

const clear = (n) => { while (n.firstChild) n.removeChild(n.firstChild); };
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/* ------------------------------------------------------------ stylesheet */

/**
 * One stylesheet, injected once. Class names mirror the canvas's structure;
 * literal values are the canvas's. Colours go through `--mb-*` custom
 * properties so `applyTheme()` can repoint the whole screen.
 */
const CSS = `
.mb-dbg{--mb-heat-grad:${HEAT_GRADIENTS.blackbody};
  display:flex;flex-direction:column;min-width:1560px;height:100%;min-height:820px;
  background:var(--mb-pg);border:1px solid var(--mb-bd);border-radius:14px;
  overflow:hidden;color:var(--mb-tx);
  font-family:var(--mb-headFont);font-size:13px;line-height:1.4}
.mb-dbg *{box-sizing:border-box}
.mb-dbg button{font:inherit;color:inherit;background:none;border:none;padding:0;
  cursor:pointer;text-align:left}
.mb-dbg button:focus-visible,.mb-dbg [tabindex]:focus-visible{
  outline:2px solid var(--mb-amb);outline-offset:2px}
.mb-mono{font-family:var(--mb-monoFont)}
@keyframes mb-pulse{0%,100%{opacity:1}50%{opacity:.45}}

/* ---- top bar (canvas: height 56px, padding 0 20px) ---- */
.mb-bar{display:flex;align-items:center;gap:14px;height:56px;padding:0 20px;
  border-bottom:1px solid var(--mb-barBd);background:var(--mb-bar);flex:none}
.mb-logo{display:flex;gap:3px;align-items:flex-end;height:18px}
.mb-logo i{width:4px;border-radius:2px;display:block}
.mb-logo i:nth-child(1){height:18px;background:var(--mb-acc)}
.mb-logo i:nth-child(2){height:9px;background:var(--mb-logo2)}
.mb-logo i:nth-child(3){height:13px;background:var(--mb-amb)}
.mb-title{font-weight:700;font-size:15px;letter-spacing:.02em}
.mb-file{font-family:var(--mb-monoFont);font-size:12px;color:var(--mb-mut);
  background:var(--mb-in1);border:1px solid var(--mb-bd);border-radius:6px;
  padding:3px 9px}
.mb-spring{flex:1}
.mb-ctrls{display:flex;gap:8px;align-items:center}
.mb-btn{display:flex;align-items:center;gap:6px;padding:7px 14px;border-radius:8px;
  background:var(--mb-in1);border:1px solid var(--mb-in1Bd);font-size:13px;
  color:var(--mb-sub);cursor:pointer;white-space:nowrap}
.mb-btn.mb-quiet{padding:7px 12px;color:var(--mb-mut)}
.mb-btn.mb-primary{padding:7px 18px;background:var(--mb-acc);color:var(--mb-accTx);
  border-color:transparent;font-weight:600}
.mb-btn[disabled]{opacity:.4;cursor:not-allowed}
.mb-btn:not([disabled]):hover{border-color:var(--mb-mut)}
.mb-counters{text-align:right}
.mb-counters .mb-step{font-family:var(--mb-monoFont);font-size:16px;font-weight:600}
.mb-counters .mb-sub{font-size:11px;color:var(--mb-faint)}
.mb-pill{padding:5px 12px;border-radius:999px;font-size:12px;font-weight:600;
  white-space:nowrap;
  background:color-mix(in oklab,var(--mb-acc) 16%,transparent);
  border:1px solid color-mix(in oklab,var(--mb-acc) 45%,transparent);
  color:var(--mb-accSoft)}
.mb-pill.mb-calm{background:var(--mb-in1);border-color:var(--mb-in1Bd);color:var(--mb-mut)}
.mb-pill.mb-live{background:color-mix(in oklab,var(--mb-grn) 16%,transparent);
  border-color:color-mix(in oklab,var(--mb-grn) 45%,transparent);color:var(--mb-grn)}

/* ---- body: canvas grid 430px 1fr 300px, gap 14, padding 14 ---- */
.mb-body{display:grid;grid-template-columns:430px minmax(0,1fr) 300px;gap:14px;
  padding:14px;flex:1;min-height:0}
.mb-panel{background:var(--mb-pn);border:1px solid var(--mb-pnBd);border-radius:10px;
  display:flex;flex-direction:column;overflow:hidden;min-height:0}
.mb-phead{display:flex;align-items:center;justify-content:space-between;
  padding:12px 14px;border-bottom:1px solid var(--mb-hd);flex:none}
.mb-ptitle{font-size:11px;letter-spacing:.14em;color:var(--mb-faint);font-weight:600}
.mb-pnote{font-family:var(--mb-monoFont);font-size:11px;color:var(--mb-dim)}
.mb-pfoot{margin-top:auto;padding:10px 14px;border-top:1px solid var(--mb-hd);
  font-size:11px;color:var(--mb-dim);flex:none}

/* ---- disassembly ---- */
.mb-dsm-cols,.mb-dsm-row{display:grid;
  grid-template-columns:24px 58px 30px 40px 44px minmax(0,1fr)}
.mb-dsm-cols{padding:6px 14px 2px;font-size:10px;letter-spacing:.1em;
  color:var(--mb-ghost);flex:none}
.mb-dsm-list{display:flex;flex-direction:column;padding:2px 6px 8px;
  overflow-y:auto;min-height:0}
.mb-dsm-row{align-items:center;padding:4px 8px;border-radius:6px;
  font-family:var(--mb-monoFont);font-size:12.5px;
  border-left:2px solid transparent;background:transparent}
.mb-dsm-row.mb-cur{border-left-color:var(--mb-acc);
  background:linear-gradient(90deg,color-mix(in oklab,var(--mb-acc) 18%,transparent),transparent)}
.mb-dsm-row span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mb-gut{color:var(--mb-acc);font-size:11px;cursor:pointer;min-height:18px}
.mb-gut:hover::after{content:"○";color:var(--mb-dim)}
.mb-gut.mb-has::after{content:none}
.mb-dsm-addr{cursor:pointer}
.mb-dsm-fx{font-size:11.5px}

/* ---- memory heat map ---- */
.mb-memwrap{position:relative;display:flex;gap:10px;padding:14px;
  flex:1;min-height:0;overflow:auto}
.mb-rowlab{display:flex;flex-direction:column;justify-content:space-between;
  padding:2px 0;font-family:var(--mb-monoFont);font-size:9.5px;
  color:var(--mb-ghost);text-align:right}
.mb-rowlab div{height:22px;line-height:22px}
.mb-grid{display:grid;grid-template-columns:repeat(${MEM_COLS},22px);gap:3px}
.mb-cell{width:22px;height:22px;border-radius:4px;display:flex;align-items:center;
  justify-content:center;font-family:var(--mb-monoFont);font-size:10px;
  font-weight:600;cursor:pointer;outline-offset:1px}
.mb-cell.mb-sel{outline:2px solid var(--mb-hoverRing)}
.mb-tip{position:absolute;z-index:3;background:var(--mb-tipBg);
  border:1px solid var(--mb-tipBd);border-radius:9px;padding:10px 12px;
  box-shadow:var(--mb-tipShadow);width:196px;pointer-events:none}
.mb-tip h4{font-family:var(--mb-monoFont);font-size:12px;font-weight:600;
  color:var(--mb-tx);margin:0}
.mb-tip dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:2px 12px;
  margin:6px 0 0;font-size:11px;color:var(--mb-mut)}
.mb-tip dd{margin:0;font-family:var(--mb-monoFont);color:var(--mb-tx);
  overflow:hidden;text-overflow:ellipsis}
.mb-tip .mb-tipfoot{margin-top:8px;padding-top:8px;border-top:1px solid var(--mb-in2Bd);
  font-size:10.5px;color:var(--mb-dim)}
.mb-legend{display:flex;align-items:center;gap:12px;padding:0 14px 12px;
  margin-left:52px;flex:none}
.mb-legend .mb-lg-txt{font-size:10.5px;color:var(--mb-dim)}
.mb-legend .mb-lg-bar{flex:1;height:8px;border-radius:4px;background:var(--mb-heat-grad)}
.mb-chip{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;
  color:var(--mb-cyn)}
.mb-chip i{width:10px;height:10px;border-radius:3px;display:block}
.mb-selline{display:flex;align-items:center;gap:14px;padding:10px 14px;
  border-top:1px solid var(--mb-hd);font-family:var(--mb-monoFont);font-size:12px;
  margin-top:auto;flex:none}
.mb-tag{padding:2px 8px;border-radius:5px;background:var(--mb-in1);
  border:1px solid var(--mb-bd);font-family:var(--mb-monoFont);font-size:11px;
  color:var(--mb-dim)}
.mb-tag.mb-on{background:var(--mb-dChip);border-color:var(--mb-dChipBd);
  color:var(--mb-dChipTx)}
button.mb-tag{cursor:pointer}

/* ---- right column ---- */
.mb-right{display:flex;flex-direction:column;gap:14px;min-height:0}
.mb-card{background:var(--mb-pn);border:1px solid var(--mb-pnBd);border-radius:10px;
  padding:14px;flex:none}
.mb-card.mb-grow{flex:1;min-height:0;display:flex;flex-direction:column}
.mb-reg{display:flex;align-items:baseline;gap:10px;padding:8px 10px;border-radius:8px;
  background:var(--mb-in1);border:1px solid var(--mb-in2Bd)}
.mb-reg .mb-n{font-weight:700;font-size:14px;width:14px;flex:none}
.mb-reg .mb-v{font-family:var(--mb-monoFont);font-size:17px;font-weight:600}
.mb-reg .mb-next{font-family:var(--mb-monoFont);font-size:12px;color:var(--mb-faint)}
.mb-reg .mb-rsub{margin-left:auto;font-size:10.5px;color:var(--mb-dim);
  white-space:nowrap}
.mb-prev-row{display:flex;gap:8px;align-items:center;font-family:var(--mb-monoFont);
  font-size:11.5px}
.mb-prev-row i{width:6px;height:6px;border-radius:50%;flex:none;display:block}
.mb-prev-row span{color:var(--mb-sub);overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.mb-prev-row em{font-style:normal;color:var(--mb-dim)}
.mb-bp{display:flex;align-items:center;gap:8px;padding:7px 9px;border-radius:7px;
  background:var(--mb-in1);border:1px solid var(--mb-in2Bd);
  font-family:var(--mb-monoFont);font-size:11.5px;width:100%}
.mb-bp .mb-bptag{color:var(--mb-amb);font-size:10.5px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.mb-bp .mb-bphits{margin-left:auto;color:var(--mb-dim);font-size:10.5px;flex:none}
.mb-bp .mb-x{flex:none;color:var(--mb-dim);padding:0 2px;visibility:hidden}
.mb-bp:hover .mb-x{visibility:visible}
.mb-empty{font-size:11px;color:var(--mb-dim);line-height:1.7}

/* ---- bottom: timeline + output (canvas grid 1fr 340px) ---- */
.mb-foot{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:14px;
  padding:0 14px 14px;flex:none}
.mb-tl{background:var(--mb-pn);border:1px solid var(--mb-pnBd);border-radius:10px;
  padding:14px 16px}
.mb-tl-head{display:flex;align-items:baseline;gap:12px;margin-bottom:10px}
.mb-tl-stat{font-family:var(--mb-monoFont);font-size:11.5px;color:var(--mb-mut)}
.mb-tl-hint{margin-left:auto;font-size:11px;color:var(--mb-dim)}
.mb-ov{position:relative;height:22px;border-radius:5px;overflow:hidden;
  background:var(--mb-hatch)}
.mb-ov-lost{position:absolute;left:0;top:0;bottom:0;cursor:not-allowed}
.mb-ov-live{position:absolute;top:0;bottom:0;
  background:linear-gradient(90deg,color-mix(in oklab,var(--mb-acc) 8%,transparent),
    color-mix(in oklab,var(--mb-acc) 22%,transparent))}
.mb-ov-edge{position:absolute;top:0;bottom:0;width:1px;background:var(--mb-mark)}
.mb-ov-head{position:absolute;top:0;bottom:0;width:10px;
  background:linear-gradient(90deg,#8c2620,var(--mb-acc))}
.mb-ov-cur{position:absolute;top:0;bottom:0;width:2px;background:var(--mb-tx)}
.mb-ov-lab{position:absolute;top:-1px;font-size:9px;color:var(--mb-ghost);
  padding-left:3px;pointer-events:none;white-space:nowrap}
.mb-wedge{height:16px;position:relative}
.mb-wedge i{position:absolute;inset:0;display:block;
  background:color-mix(in oklab,var(--mb-acc) 12%,transparent)}
.mb-zoom{position:relative;height:44px;border-radius:8px;background:var(--mb-tlBg);
  border:1px solid var(--mb-tlBd);overflow:visible;touch-action:none;
  user-select:none;-webkit-user-select:none}
.mb-zoom.mb-dead{cursor:not-allowed;opacity:.55}
.mb-zoom:not(.mb-dead){cursor:pointer}
.mb-zoom-ticks{position:absolute;inset:0;border-radius:8px;
  background:repeating-linear-gradient(90deg,transparent 0 19.6%,var(--mb-tick) 19.6% 20%)}
.mb-zoom-fill{position:absolute;left:0;top:0;bottom:0;border-radius:8px 0 0 8px;
  background:linear-gradient(90deg,color-mix(in oklab,var(--mb-acc) 6%,transparent),
    color-mix(in oklab,var(--mb-acc) 18%,transparent))}
.mb-zoom-ghost{position:absolute;top:0;bottom:0;width:2px;
  background:color-mix(in oklab,var(--mb-tx) 45%,transparent);display:none}
.mb-knob{position:absolute;top:-7px;bottom:-7px;width:16px;transform:translateX(-50%);
  border-radius:6px;background:var(--mb-acc);cursor:grab;display:flex;
  align-items:center;justify-content:center;
  box-shadow:0 0 0 3px color-mix(in oklab,var(--mb-acc) 30%,transparent),
    0 4px 14px rgba(0,0,0,.5)}
.mb-knob:active{cursor:grabbing}
.mb-knob i{width:2px;height:16px;border-radius:1px;background:var(--mb-knobIn);
  box-shadow:4px 0 0 var(--mb-knobIn),-4px 0 0 var(--mb-knobIn);display:block}
.mb-marks{display:flex;flex-wrap:wrap;gap:6px;margin-top:14px;align-items:center}
.mb-marks .mb-mk{padding:1px 7px;border-radius:5px;font-family:var(--mb-monoFont);
  font-size:10px;border:1px solid var(--mb-in1Bd);background:var(--mb-in1)}
.mb-tl-foot{display:flex;justify-content:space-between;margin-top:14px;
  font-family:var(--mb-monoFont);font-size:10.5px;color:var(--mb-dim)}
.mb-out{background:var(--mb-pn);border:1px solid var(--mb-pnBd);border-radius:10px;
  padding:14px 16px;display:flex;flex-direction:column;min-height:0}
.mb-out-box{flex:1;background:var(--mb-outBg);border:1px solid var(--mb-outBd);
  border-radius:7px;padding:10px 12px;font-family:var(--mb-monoFont);font-size:14px;
  color:var(--mb-outTx);overflow:auto;white-space:pre-wrap;word-break:break-all;
  min-height:64px;max-height:132px}
.mb-caret{display:inline-block;width:8px;height:16px;background:var(--mb-acc);
  vertical-align:-3px;margin-left:2px;animation:mb-pulse 1.2s infinite}
.mb-err[hidden]{display:none}
.mb-err{margin:0 14px 12px;padding:8px 12px;border-radius:8px;font-size:12px;
  background:color-mix(in oklab,#8c2620 30%,transparent);
  border:1px solid #8c2620;color:var(--mb-accSoft);
  display:flex;gap:10px;align-items:center}
`;

function ensureStyles(doc) {
  if (doc.getElementById("mb-debugger-css")) return;
  doc.head.appendChild(createElement("style", { id: "mb-debugger-css", text: CSS }));
}

/* ------------------------------------------------------------------ screen */

/**
 * Mount canvas 1a into `root`.
 *
 * @param {HTMLElement} root      container; emptied and filled.
 * @param {object} session        a `bridge.js` session. Commands are optional:
 *                                anything missing simply disables its control.
 * @param {object} [options]
 * @param {string} [options.fileName]  shown in the top-bar chip.
 * @param {string} [options.theme]     "dark" (default) or "light".
 * @param {string} [options.palette]   heat ramp: "blackbody" | "toxic" | "paper".
 * @param {Function} [options.onExplain] 展开讲解 -- canvas 1b, not built in v1.
 * @param {Function} [options.onReset]   fallback when the session has no reset().
 * @returns {object} controller: `{el, applySnapshot, applyProgress,
 *   applyStopped, applyError, setOutput, setFileName, setTheme, destroy}`.
 */
export function mountDebugger(root, session = {}, options = {}) {
  ensureStyles(root.ownerDocument || document);

  const bindings = [];
  // Only UI expressions explicitly marked in buildSkeleton are bound. Raw
  // program output, file names, breakpoint conditions and errors bypass this.
  function el(tag, attrs = {}, ...kids) {
    const resolved = { ...attrs };
    const pending = [];
    for (const [key, value] of Object.entries(attrs)) {
      if (typeof value === 'function' && !key.startsWith('on')) {
        resolved[key] = value();
        pending.push((node) => { if (key === 'text') node.textContent = value(); else node.setAttribute(key, value()); });
      }
    }
    const node = createElement(tag, resolved, ...kids.map(kid => {
      if (typeof kid !== 'function') return kid;
      const text = document.createTextNode(kid());
      bindings.push(() => { text.textContent = kid(); });
      return text;
    }));
    for (const update of pending) bindings.push(() => update(node));
    return node;
  }

  const state = {
    snap: null,
    running: false,
    liveStep: null,          // from `progress`, valid only while running
    memOffset: 0,
    memCount: MEM_COUNT,
    disasmCount: DISASM_COUNT,
    selected: null,          // pinned memory address
    hover: null,
    heatScale: "log",
    palette: options.palette || "blackbody",
    theme: options.theme || "dark",
    fileName: options.fileName || "",
    chunk: CHUNKS[1],
    output: null,            // null = the snapshot never carried the text
    stopReason: null,
    dragging: false,
  };

  const ui = buildSkeleton();
  const frame = ui.frame;
  clear(root);
  root.appendChild(frame);
  applyTheme(frame, state.theme);
  frame.style.setProperty("--mb-heat-grad", HEAT_GRADIENTS[state.palette]);

  /* --------------------------------------------------------- command edge */

  const call = (name, ...args) => {
    const fn = session && session[name];
    if (typeof fn !== "function") return false;
    try { fn.call(session, ...args); } catch (e) { showError(String(e && e.message || e)); }
    return true;
  };

  const reSnapshot = () => call("snapshot", {
    memOffset: state.memOffset,
    memCount: state.memCount,
    disasmCount: state.disasmCount,
  });

  /**
   * Ask once for the window this screen's geometry actually needs.
   *
   * Deliberately not called at mount: `mountDebugger()` must not assume a
   * program is already loaded. Requesting a snapshot before `load()` reaches
   * the worker gets a `no_program` error, which is a timing accident rather
   * than anything a reader could act on -- and the screen has to survive
   * "mount empty, let the user pick a program" as much as it survives
   * "load first, then mount". So the request waits for the first snapshot to
   * arrive on its own, and only fires if that snapshot is a different size
   * from what the heat map needs (`load` replies with the default 24 cells).
   * 288 cells cost 0.24 ms server-side (§5.2), so the extra round trip is not
   * worth economising.
   */
  let windowRequested = false;
  const requestWindow = () => {
    if (windowRequested) return;
    windowRequested = true;
    reSnapshot();
  };

  /* ------------------------------------------------------------ skeleton */

  function buildSkeleton() {
    const o = {};

    // ---- top bar -------------------------------------------------------
    o.file = el("div", { class: "mb-file" });
    o.btnBack = el("button", { class: "mb-btn", title: () => (tr("m1")) }, () => (tr("m2")));
    o.btnStep = el("button", { class: "mb-btn", title: () => (tr("m3")) }, () => (tr("m4")));
    o.btnRun = el("button", { class: "mb-btn mb-primary", title: () => (tr("m5")) }, () => (tr("m6")));
    o.btnChunk = el("button", {
      class: "mb-btn mb-quiet",
      title: () => (tr("m7")),
    });
    o.btnReset = el("button", { class: "mb-btn mb-quiet", title: () => (tr("m8")) }, () => (tr("m9")));
    o.stepNum = el("div", { class: "mb-step" });
    o.stepSub = el("div", { class: "mb-sub" });
    o.pill = el("div", { class: "mb-pill" });

    const bar = el("div", { class: "mb-bar" },
      el("div", { class: "mb-logo" }, el("i"), el("i"), el("i")),
      el("div", { class: "mb-title", text: "pyMalbolge" }),
      o.file,
      el("div", { class: "mb-spring" }),
      el("div", { class: "mb-ctrls" },
        o.btnBack, o.btnStep, o.btnRun, o.btnChunk, o.btnReset),
      el("div", { class: "mb-spring" }),
      el("div", { class: "mb-counters" }, o.stepNum, o.stepSub),
      o.pill);

    // ---- disassembly ---------------------------------------------------
    o.dsmNote = el("div", { class: "mb-pnote" });
    o.dsmList = el("div", { class: "mb-dsm-list" });
    o.dsmFoot = el("div", { class: "mb-pfoot" });
    const dsm = el("div", { class: "mb-panel" },
      el("div", { class: "mb-phead" },
        el("div", { class: "mb-ptitle", text: () => (tr("m10")) }), o.dsmNote),
      el("div", { class: "mb-dsm-cols" },
        el("span"), el("span", { text: () => (tr("m11")) }), el("span", { text: () => (tr("m12")) }),
        el("span", { text: () => (tr("m13")) }), el("span", { text: () => (tr("m14")) }),
        el("span", { text: () => (tr("m15")) })),
      o.dsmList, o.dsmFoot);

    // ---- memory --------------------------------------------------------
    o.memRange = el("span", { class: "mb-tag" });
    o.memFollow = el("button", { class: "mb-tag mb-on", title: () => (tr("m16")) });
    o.memC = el("span", { class: "mb-tag" });
    o.rowLab = el("div", { class: "mb-rowlab" });
    o.grid = el("div", {
      class: "mb-grid", role: "grid",
      "aria-label": () => (tr("m17")),
    });
    o.tip = el("div", { class: "mb-tip", hidden: true });
    o.peak = el("span", { class: "mb-lg-txt" });
    o.scaleBtn = el("button", {
      class: "mb-tag",
      title: () => (tr("m18")
           + tr("m19")
           + tr("m20")),
    });
    o.legendBar = el("div", { class: "mb-lg-bar" });
    o.selLine = el("div", { class: "mb-selline" });

    const memWrap = el("div", { class: "mb-memwrap" }, o.rowLab, o.grid, o.tip);
    const mem = el("div", { class: "mb-panel" },
      el("div", { class: "mb-phead" },
        el("div", { class: "mb-ptitle", text: () => (tr("m21")) }),
        el("div", { class: "mb-pnote", style: { display: "flex", gap: "8px", alignItems: "center" } },
          o.memRange, o.memFollow, o.memC)),
      memWrap,
      el("div", { class: "mb-legend" },
        el("span", { class: "mb-lg-txt", text: () => (tr("m22")) }),
        o.legendBar,
        o.peak,
        o.scaleBtn,
        el("span", { class: "mb-chip" },
          el("i", { style: { boxShadow: "0 0 0 2px var(--mb-dRing) inset" } }), () => (tr("m23"))),
        el("span", { class: "mb-chip", style: { color: "var(--mb-acc)" } },
          el("i", { style: { boxShadow: "0 0 0 2px var(--mb-acc) inset" } }), () => (tr("m24"))),
        el("span", { class: "mb-chip", style: { color: "var(--mb-wRing)" } },
          el("i", { style: { boxShadow: "0 0 0 2px var(--mb-wRing) inset" } }), () => (tr("m25")))),
      o.selLine);

    // ---- right column --------------------------------------------------
    o.regs = el("div", { style: { display: "flex", flexDirection: "column", gap: "10px" } });
    o.prevList = el("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } });
    o.explain = el("button", {
      class: "mb-ptitle",
      style: { color: "var(--mb-amb)", letterSpacing: "0", fontSize: "11px" },
      text: () => (tr("m26")),
    });
    o.bpList = el("div", {
      style: { display: "flex", flexDirection: "column", gap: "7px",
               overflowY: "auto", minHeight: "0" },
    });

    const right = el("div", { class: "mb-right" },
      el("div", { class: "mb-card" },
        el("div", { class: "mb-ptitle", style: { marginBottom: "10px" }, text: () => (tr("m27")) }),
        o.regs),
      el("div", { class: "mb-card" },
        el("div", { style: { display: "flex", justifyContent: "space-between",
                             alignItems: "center", marginBottom: "10px" } },
          el("span", { class: "mb-ptitle", text: () => (tr("m28")) }), o.explain),
        o.prevList),
      el("div", { class: "mb-card mb-grow" },
        el("div", { class: "mb-ptitle", style: { marginBottom: "10px" }, text: () => (tr("m29")) }),
        o.bpList));

    // ---- timeline ------------------------------------------------------
    o.tlStat = el("div", { class: "mb-tl-stat" });
    o.tlHint = el("div", { class: "mb-tl-hint" });
    o.ovLost = el("div", { class: "mb-ov-lost", title: () => (tr("m30")) });
    o.ovLive = el("div", { class: "mb-ov-live" });
    o.ovEdge = el("div", { class: "mb-ov-edge" });
    o.ovLab = el("div", { class: "mb-ov-lab" });
    o.ovCur = el("div", { class: "mb-ov-cur" });
    o.ovHead = el("div", { class: "mb-ov-head", style: { right: "0" } });
    o.wedge = el("i");
    o.zoomFill = el("div", { class: "mb-zoom-fill" });
    o.zoomGhost = el("div", { class: "mb-zoom-ghost" });
    o.knob = el("div", {
      class: "mb-knob", role: "slider", tabindex: "0",
      "aria-label": () => (tr("m31")),
    }, el("i"));
    o.zoom = el("div", { class: "mb-zoom" },
      el("div", { class: "mb-zoom-ticks" }), o.zoomFill, o.zoomGhost, o.knob);
    o.marks = el("div", { class: "mb-marks" });
    o.tlA = el("span"); o.tlB = el("span"); o.tlC = el("span");

    const tl = el("div", { class: "mb-tl" },
      el("div", { class: "mb-tl-head" },
        el("span", { class: "mb-ptitle", text: () => (tr("m32")) }), o.tlStat, o.tlHint),
      el("div", { class: "mb-ov" }, o.ovLost, o.ovLive, o.ovEdge, o.ovLab, o.ovCur, o.ovHead),
      el("div", { class: "mb-wedge" }, o.wedge),
      o.zoom, o.marks,
      el("div", { class: "mb-tl-foot" }, o.tlA, o.tlB, o.tlC));

    // ---- output --------------------------------------------------------
    o.outCount = el("span", { style: { fontSize: "11px", color: "var(--mb-dim)" } });
    o.outBox = el("div", { class: "mb-out-box" });
    const out = el("div", { class: "mb-out" },
      el("div", { style: { display: "flex", justifyContent: "space-between",
                           marginBottom: "8px" } },
        el("span", { class: "mb-ptitle", text: () => (tr("m33")) }), o.outCount),
      o.outBox);

    o.err = el("div", { class: "mb-err", hidden: true });
    o.frame = el("div", { class: "mb-dbg" },
      bar, o.err,
      el("div", { class: "mb-body" }, dsm, mem, right),
      el("div", { class: "mb-foot" }, tl, out));
    return o;
  }

  /* ------------------------------------------------------------ rendering */

  function render() {
    const s = state.snap;
    if (!s) return;
    renderBar(s);
    renderDisasm(s);
    renderMemory(s);
    renderRegisters(s);
    renderPreview(s);
    renderBreakpoints(s);
    renderTimeline(s);
    renderOutput(s);
  }

  // ---- top bar ---------------------------------------------------------
  function renderBar(s) {
    const r = s.registers, tl = s.timeline;
    ui.file.textContent = state.fileName || tr("m34");
    ui.file.hidden = !state.fileName;

    const step = state.running && state.liveStep != null ? state.liveStep : r.step;
    ui.stepNum.textContent = `${tr("m35")}${fmt(step)}`;

    // The 10,000-cap is not a snapshot field; when history has saturated it is
    // exactly the width of `seekable`, and before that there is no cap to show.
    const cap = tl.seekable[0] > 0 ? tl.seekable[1] - tl.seekable[0] : null;
    ui.stepSub.textContent =
      `${tr("m36")}${fmt(r.history_size)}${cap ? ` / ${fmt(cap)}` : ""}`
      + `${tr("m37")}${fmt(r.input_consumed)}/${fmt(r.input_total)}`;

    const { text, tone } = statusPill(s);
    ui.pill.textContent = text;
    ui.pill.className = `mb-pill${tone ? ` mb-${tone}` : ""}`;

    ui.btnRun.textContent = state.running ? tr("m38") : tr("m39");
    ui.btnChunk.textContent = `⏩ ×${fmt(state.chunk)}`;
    const dead = r.terminated;
    ui.btnStep.disabled = dead || state.running || typeof session.step !== "function";
    ui.btnBack.disabled = state.running || r.history_size <= 0
      || typeof session.back !== "function";
    ui.btnRun.disabled = (dead && !state.running) || typeof session.run !== "function";
    ui.btnReset.disabled = state.running
      || (typeof session.reset !== "function" && typeof options.onReset !== "function");
    ui.explain.disabled = typeof options.onExplain !== "function";
    ui.explain.style.opacity = ui.explain.disabled ? ".4" : "1";
    ui.explain.title = ui.explain.disabled
      ? tr("m40")
      : tr("m41");
  }

  function statusPill(s) {
    const r = s.registers;
    if (state.running) return { text: tr("m42"), tone: "live" };
    if (r.terminated) return { text: tr("m43"), tone: "calm" };
    const reason = state.stopReason || r.stop_reason;
    if (reason === "breakpoint") {
      const bp = (s.breakpoints.breakpoints || []).find((b) => b.addr === r.c);
      return {
        text: `${tr("m46")}${pad5(r.c)}${bp ? `${tr("m44")}${fmt(bp.hit_count)}${tr("m45")}` : ""}`,
        tone: "",
      };
    }
    if (reason === "watchpoint") return { text: `${tr("m47")}`, tone: "" };
    if (reason === "error") return { text: tr("m48"), tone: "" };
    if (reason === "input_exhausted") return { text: tr("m49"), tone: "" };
    // `stop_reason` is "running" whenever the debugger is not *stopped* for a
    // reason -- including after a plain step() -- so it is not evidence that
    // anything is executing. `state.running`, driven by run/stopped events, is.
    const label = reason === "running" ? tr("m50") : (semanticText(STOP_REASON_TEXT[reason]) || tr("m51"));
    return { text: `⏸ ${label}`, tone: "calm" };
  }

  // ---- disassembly -----------------------------------------------------
  function renderDisasm(s) {
    const d = s.disasm, ops = opColors(state.theme);
    ui.dsmNote.textContent =
      `${pad5(d.window[0])}–${pad5(d.window[1])}${tr("m52")}`;
    // The contract gives DisasmView no scroll offset -- the window is always
    // centred on C -- so "跟随 C" is a statement of fact, not a toggle.
    ui.dsmNote.title = tr("m53");

    clear(ui.dsmList);
    for (const r of d.rows) {
      const exec = !NON_EXEC.has(r.effect);
      const row = el("div", {
        class: `mb-dsm-row${r.is_current ? " mb-cur" : ""}`,
        "data-addr": r.addr,
      });
      row.appendChild(el("button", {
        class: `mb-gut${r.has_breakpoint ? " mb-has" : ""}`,
        title: r.has_breakpoint ? tr("m54") : tr("m55"),
        "aria-label": `${r.has_breakpoint ? tr("m56") : tr("m57")}${tr("m58")}${pad5(r.addr)}`,
        text: r.is_current ? "▶" : (r.has_breakpoint ? "●" : ""),
        style: { color: r.has_breakpoint && !r.is_current ? "var(--mb-acc)" : "" },
        onclick: () => call("breakpoint", r.addr, "toggle"),
      }));
      row.appendChild(el("span", {
        class: "mb-dsm-addr", text: pad5(r.addr),
        title: tr("m59"),
        style: { color: r.is_current ? "var(--mb-tx)" : "var(--mb-faint)" },
        ondblclick: () => jumpMemory(r.addr),
      }));
      row.appendChild(el("span", {
        text: r.char,
        style: { color: exec ? "var(--mb-tx)" : "var(--mb-dim)" },
      }));
      row.appendChild(el("span", {
        text: String(r.raw), style: { color: "var(--mb-faint)" },
      }));
      row.appendChild(el("span", {
        text: r.mnemonic, style: {
          fontWeight: "600",
          color: r.is_current ? "var(--mb-amb)"
               : (exec ? (ops[r.mnemonic] || "var(--mb-tx)") : "var(--mb-ghost)"),
        },
      }));
      row.appendChild(el("span", {
        class: "mb-dsm-fx",
        text: semanticText(EFFECT_TEXT[r.effect]) || r.effect,
        title: (semanticText(EFFECT_TEXT[r.effect]) || r.effect) + (r.opcode == null ? "" : ` · opcode (${r.raw} + ${r.addr}) % 94 = ${r.opcode}`),
        style: { color: r.is_current ? "var(--mb-sub)" : "var(--mb-dim)" },
      }));
      ui.dsmList.appendChild(row);
    }

    const cur = d.rows.find((r) => r.is_current);
    clear(ui.dsmFoot);
    ui.dsmFoot.append(
      tr("m60"),
      el("span", {
        style: { color: "var(--mb-amb)" },
        text: cur && s.teaching.encrypt
          ? `${JSON.stringify(cur.char)}+${s.teaching.encrypt.index}${tr("m61")}`
            + `${JSON.stringify(s.teaching.encrypt.new_char)}`
          : tr("m62"),
      }));
  }

  function jumpMemory(addr) {
    const s = state.snap;
    if (!s) return;
    state.memOffset = addr - s.memory.d;
    if (!reSnapshot()) return;
  }

  // ---- memory ----------------------------------------------------------
  function renderMemory(s) {
    const m = s.memory;
    const cols = MEM_COLS;
    const rows = Math.ceil(m.cells.length / cols);
    const end = m.start + m.cells.length - 1;

    ui.memRange.textContent = `${pad5(m.start)}–${pad5(end)}`;
    ui.memFollow.textContent = m.offset === 0
      ? tr("m63") : `${tr("m64")}${m.offset > 0 ? "+" : ""}${fmt(m.offset)}`;
    ui.memFollow.classList.toggle("mb-on", m.offset === 0);
    ui.memFollow.onclick = () => { state.memOffset = 0; reSnapshot(); };
    ui.memC.textContent = m.c < m.start ? `C=${pad5(m.c)}${tr("m65")}`
      : m.c > end ? `C=${pad5(m.c)}${tr("m66")}` : `C=${pad5(m.c)}${tr("m67")}`;

    clear(ui.rowLab);
    for (let r = 0; r < rows; r++) {
      ui.rowLab.appendChild(el("div", { text: pad5(m.start + r * cols) }));
    }

    clear(ui.grid);
    for (const c of m.cells) {
      const t = heatT(c.heat, m.heat_max, state.heatScale);
      const shadows = [];
      if (c.is_d) {
        shadows.push("0 0 0 2px var(--mb-dRing) inset",
          "0 0 14px color-mix(in oklab,var(--mb-acc) 60%,transparent)");
      }
      if (c.just_written) shadows.push("0 0 0 2px var(--mb-wRing)");
      if (c.is_c) {
        shadows.push(c.just_written ? "0 0 0 3px var(--mb-acc)"
                                    : "0 0 0 2px var(--mb-acc)");
      }
      const cell = el("div", {
        class: `mb-cell${state.selected === c.addr ? " mb-sel" : ""}`,
        role: "gridcell", tabindex: "-1",
        "data-addr": c.addr,
        "aria-label": `mem[${c.addr}] = ${c.value}${tr("m68")}${c.heat}${tr("m69")}`,
        text: c.is_d ? "D" : (c.is_c ? "C" : ""),
        style: {
          background: heatColor(t, state.palette),
          boxShadow: shadows.join(","),
          color: c.is_d ? "var(--mb-accTx)"
               : (c.is_c ? "var(--mb-tx)" : "transparent"),
        },
      });
      ui.grid.appendChild(cell);
    }
    renderSelLine(s);

    ui.peak.textContent = `${tr("m70")}${fmt(m.heat_max)}${tr("m71")}`;
    ui.scaleBtn.textContent = state.heatScale === "log" ? tr("m72") : tr("m73");
    ui.scaleBtn.onclick = () => {
      state.heatScale = state.heatScale === "log" ? "linear" : "log";
      if (state.snap) renderMemory(state.snap);
    };
    ui.legendBar.style.background = HEAT_GRADIENTS[state.palette];
  }

  function cellAt(addr) {
    const m = state.snap && state.snap.memory;
    return m ? m.cells.find((c) => c.addr === addr) : null;
  }

  function renderSelLine(s) {
    const m = s.memory;
    clear(ui.selLine);
    const c = state.selected != null ? cellAt(state.selected) : null;
    if (!c) {
      ui.selLine.appendChild(el("span", {
        style: { color: "var(--mb-dim)", fontSize: "11px" },
        text: tr("m74"),
      }));
      return;
    }
    const wp = (s.breakpoints.watchpoints || []).find((w) => w.addr === c.addr);
    ui.selLine.append(
      el("span", { style: { color: "var(--mb-faint)", fontSize: "11px" }, text: tr("m75") }),
      el("span", { style: { color: "var(--mb-tx)" }, text: `mem[${c.addr}]` }),
      el("span", { style: { color: "var(--mb-mut)" }, text: `= ${fmt(c.value)}` }),
      el("span", { style: { color: "var(--mb-dim)" }, text: charNote(c) }),
      el("span", { style: { color: "var(--mb-amb)" }, text: `${tr("m76")}${fmt(c.heat)}${tr("m77")}` }),
      wp ? el("span", { style: { color: "var(--mb-grn)" }, text: tr("m78") }) : null,
      el("span", {
        style: { marginLeft: "auto", color: c.is_d ? "var(--mb-cyn)" : "var(--mb-dim)" },
        text: c.is_d ? "= D" : `${tr("m79")}${c.addr - m.d >= 0 ? "+" : ""}${fmt(c.addr - m.d)}`,
      }));
  }

  const charNote = (c) => (c.char === "." ? tr("m80") : `${JSON.stringify(c.char)}${tr("m81")}`);

  function showTip(addr, cellEl) {
    const s = state.snap, c = cellAt(addr);
    if (!s || !c) return hideTip();
    const wp = (s.breakpoints.watchpoints || []).find((w) => w.addr === addr);
    clear(ui.tip);
    ui.tip.append(
      el("h4", { text: `mem[${c.addr}]` }),
      el("dl", {},
        el("dt", { text: tr("m82") }),
        el("dd", { text: `${fmt(c.value)} · ${charNote(c)}` }),
        el("dt", { text: tr("m83") }),
        el("dd", { style: { color: "var(--mb-amb)" }, text: `${fmt(c.heat)}${tr("m84")}` }),
        el("dt", { text: tr("m85") }),
        el("dd", {
          style: { color: "var(--mb-cyn)" },
          text: `${c.addr - s.memory.d >= 0 ? "+" : ""}${fmt(c.addr - s.memory.d)}`,
        }),
        el("dt", { text: tr("m86") }),
        el("dd", {
          style: { color: wp ? "var(--mb-grn)" : "var(--mb-dim)" },
          text: wp
            ? `${tr("m88")}${wp.last_value == null ? "" : `${tr("m87")}${fmt(wp.last_value)}`}`
            : "—",
        })),
      el("div", { class: "mb-tipfoot", text: tr("m89") }));

    const wrap = ui.tip.parentElement.getBoundingClientRect();
    const box = cellEl.getBoundingClientRect();
    ui.tip.hidden = false;
    const w = ui.tip.offsetWidth || 196, h = ui.tip.offsetHeight || 120;
    ui.tip.style.left =
      `${clamp(box.left - wrap.left + 26, 8, Math.max(8, wrap.width - w - 8))}px`;
    ui.tip.style.top =
      `${clamp(box.top - wrap.top - 6, 8, Math.max(8, wrap.height - h - 8))}px`;
  }

  const hideTip = () => { ui.tip.hidden = true; };

  // ---- registers -------------------------------------------------------
  function renderRegisters(s) {
    const r = s.registers;
    // `a_char_symbol` is the glyph for a % 256 -- a real character when
    // printable (quote it, so "1" does not read as part of the sentence), a
    // control picture like U+2407 when not, and null for 0x80..0xFF.
    const sym = r.a_char_kind === "printable"
      ? JSON.stringify(r.a_char_symbol) : r.a_char_symbol;
    const aSub = r.a_char_kind === "other" || !r.a_char_symbol
      ? (semanticText(CHAR_KIND_TEXT[r.a_char_kind]) || "")
      : `ASCII ${sym} ${semanticText(CHAR_KIND_TEXT[r.a_char_kind]) || ""}`;
    const rows = [
      { n: "A", color: "var(--mb-amb)", v: r.a, next: r.next_a, sub: aSub },
      { n: "C", color: "var(--mb-acc)", v: r.c, next: r.next_c, sub: tr("m90") },
      { n: "D", color: "var(--mb-cyn)", v: r.d, next: r.next_d, sub: tr("m91") },
    ];
    clear(ui.regs);
    for (const row of rows) {
      ui.regs.appendChild(el("div", { class: "mb-reg" },
        el("span", { class: "mb-n", style: { color: row.color }, text: row.n }),
        el("span", { class: "mb-v", text: fmt(row.v) }),
        el("span", {
          class: "mb-next",
          text: `→ ${row.next == null ? "—" : fmt(row.next)}`,
          title: row.next == null ? tr("m92") : "",
        }),
        el("span", { class: "mb-rsub", text: row.sub })));
    }
  }

  // ---- next-step preview ----------------------------------------------
  function renderPreview(s) {
    const t = s.teaching;
    clear(ui.prevList);
    if (!t.effects || !t.effects.length) {
      ui.prevList.appendChild(el("div", {
        class: "mb-empty",
        text: t.terminated ? tr("m93") : tr("m94"),
      }));
      return;
    }
    for (const e of t.effects) {
      const token = EFFECT_KIND_TOKEN[e.kind] || "mut";
      const { text, detail } = localiseEffect(e, t);
      ui.prevList.appendChild(el("div", { class: "mb-prev-row" },
        el("i", { style: { background: `var(--mb-${token})` } }),
        el("span", { text, title: `${e.kind}${e.detail ? ` · ${e.detail}` : ""}` }),
        detail ? el("em", { text: detail }) : null));
    }
  }

  /**
   * `TeachingView.effects[].text` / `.detail` are English prose -- "mem[498]
   * re-encrypted", "was 53" -- which is the same mistake §3.2 fixed for
   * `DisasmView.effect`: one natural language baked into the layer both
   * renderers share. Reported upstream; until the ViewModel keys them, the two
   * cases that are actually words rather than symbols are rebuilt here from
   * the structured fields beside them, and anything else passes through
   * unchanged rather than being guessed at.
   */
  function localiseEffect(e, teaching) {
    if (e.kind === "encrypt" && teaching.encrypt) {
      const k = teaching.encrypt;
      return {
        text: `mem[${k.addr}]: ${JSON.stringify(k.old_char)} → ${JSON.stringify(k.new_char)}`,
        detail: `${k.old} → ${k.new}`,
      };
    }
    const was = /^was (.+)$/.exec(e.detail || "");
    return { text: e.text, detail: was ? `${tr("m95")}${was[1]}` : e.detail };
  }

  // ---- breakpoints / watchpoints ---------------------------------------
  function renderBreakpoints(s) {
    const b = s.breakpoints;
    clear(ui.bpList);
    const bps = b.breakpoints || [], wps = b.watchpoints || [];
    if (!bps.length && !wps.length) {
      ui.bpList.appendChild(el("div", {
        class: "mb-empty",
        text: tr("m96"),
      }));
      return;
    }
    // No UI here creates a conditional breakpoint, and that is deliberate.
    // A `Breakpoint`'s condition is a Python `Callable`, which cannot cross
    // `postMessage` -- so a condition set from the browser could only ever be
    // a `condition_text` the backend never evaluates, i.e. a breakpoint that
    // announces a rule it does not follow. An interface that ships a control
    // captioned "does not actually work" teaches the reader to distrust the
    // rest of it, so the control does not exist. `condition_text` is still
    // rendered when a snapshot carries one (breakpoints made in-process by the
    // TUI or CLI do have a real predicate beside the text). Making conditions
    // *data* rather than code -- structured, clonable, evaluated server-side --
    // is the real fix, and it is a new feature, not this screen's business.
    for (const bp of bps) {
      const row = el("div", {
        class: "mb-bp",
        style: { opacity: bp.enabled ? "1" : "0.55" },
      });
      row.append(
        el("button", {
          style: { color: bp.enabled
            ? (bp.temporary ? "var(--mb-amb)" : "var(--mb-acc)") : "var(--mb-mut)",
            flex: "none" },
          text: bp.temporary ? "◌" : "●",
          title: bp.enabled ? tr("m97") : tr("m98"),
          onclick: () => call("breakpoint", bp.addr, bp.enabled ? "disable" : "enable"),
        }),
        el("button", {
          style: { color: "var(--mb-tx)", flex: "none" },
          text: pad5(bp.addr),
          title: tr("m99"),
          onclick: () => jumpMemory(bp.addr),
        }),
        el("span", { style: { color: "var(--mb-faint)" }, text: bp.mnemonic }),
        el("span", {
          class: "mb-bptag",
          text: bp.condition_text || (bp.temporary ? tr("m100") : ""),
          title: bp.condition_text ? tr("m101") : "",
        }),
        el("span", {
          class: "mb-bphits",
          text: bp.enabled ? `${tr("m102")}${fmt(bp.hit_count)}` : tr("m103"),
        }),
        el("button", {
          class: "mb-x", text: "✕", title: tr("m104"),
          onclick: () => call("breakpoint", bp.addr, "toggle"),
        }));
      ui.bpList.appendChild(row);
    }
    for (const wp of wps) {
      ui.bpList.appendChild(el("div", {
        class: "mb-bp", style: { opacity: wp.enabled ? "1" : "0.55" },
      },
        el("span", { style: { color: "var(--mb-grn)", flex: "none" }, text: "◈" }),
        el("button", {
          style: { color: "var(--mb-tx)", flex: "none" }, text: pad5(wp.addr),
          title: tr("m105"), onclick: () => jumpMemory(wp.addr),
        }),
        el("span", { style: { color: "var(--mb-faint)" }, text: "watch" }),
        el("span", {
          class: "mb-bptag",
          text: wp.last_value == null ? "" : `${tr("m106")}${fmt(wp.last_value)}`,
        }),
        el("span", { class: "mb-bphits", text: wp.enabled ? tr("m107") : tr("m108") }),
        el("button", {
          class: "mb-x", text: "✕", title: tr("m109"),
          onclick: () => call("watchpoint", wp.addr, "toggle"),
        })));
    }
  }

  // ---- timeline --------------------------------------------------------
  /**
   * The canvas drew one continuous, fully draggable timeline. The backend
   * cannot honour that: `_max_history = 10000` and `_save_history` drops the
   * oldest entry past it, so `TimelineView.seekable[0]` is not 0 once a
   * program has run past the window (§3.5, §4.3).
   *
   * So the bar is drawn in two materially different parts:
   *   - `[0, seekable[0])` keeps the canvas's diagonal hatch, is marked
   *     `不可达 · 历史已丢弃`, carries `cursor:not-allowed`, and swallows
   *     clicks without issuing a seek;
   *   - `[seekable[0], seekable[1]]` is the solid accent band, and it is the
   *     only thing the zoom bar below it magnifies. A vertical edge plus a
   *     step label sits exactly on the boundary, and the wedge between the two
   *     bars is drawn from the band's real coordinates so the magnification is
   *     visibly of that segment and not of the whole run.
   * When nothing has been discarded the hatched part has zero width and the
   * warning disappears -- the honest case looks like the canvas.
   */
  function renderTimeline(s) {
    const tl = s.timeline;
    const [lo, hi] = tl.seekable;
    const max = Math.max(tl.max_reached, 1);
    const cur = state.running && state.liveStep != null ? state.liveStep : tl.current;
    const lost = lo > 0;

    ui.tlStat.textContent =
      `${tr("m110")}${fmt(tl.max_reached)}${tr("m111")}${fmt(cur)}`
      + `${tr("m112")}${fmt(Math.max(0, tl.max_reached - tl.current))}`;
    ui.tlHint.textContent = lost
      ? tr("m113")
      : tr("m114");
    ui.tlHint.style.color = lost ? "var(--mb-amb)" : "var(--mb-dim)";

    const pct = (v) => `${clamp((v / max) * 100, 0, 100)}%`;
    ui.ovLost.style.width = pct(lo);
    ui.ovLost.hidden = !lost;
    ui.ovLive.style.left = pct(lo);
    ui.ovLive.style.width = `${clamp(((hi - lo) / max) * 100, 0, 100)}%`;
    ui.ovEdge.style.left = pct(lo);
    ui.ovEdge.hidden = !lost;
    // Sit the label inside the dead zone when there is room for it, so the
    // words are over the thing they describe rather than over the live band.
    const roomy = lo / max >= 0.22;
    ui.ovLab.style.left = roomy ? "0" : pct(lo);
    ui.ovLab.style.right = roomy ? `${clamp(100 - (lo / max) * 100, 0, 100)}%` : "auto";
    ui.ovLab.style.textAlign = roomy ? "right" : "left";
    ui.ovLab.style.paddingRight = roomy ? "5px" : "0";
    ui.ovLab.textContent = lost
      ? (roomy ? `${tr("m115")}${fmt(lo)}${tr("m116")}` : `${tr("m117")}${fmt(lo)}${tr("m118")}`)
      : "";
    ui.ovLab.hidden = !lost;
    ui.ovCur.style.left = pct(cur);

    // Wedge: connect the live band's real edges to the full-width zoom bar.
    const l = clamp((lo / max) * 100, 0, 100), r = clamp((hi / max) * 100, 0, 100);
    ui.wedge.style.clipPath = `polygon(${l}% 0,${r}% 0,100% 100%,0 100%)`;

    const span = hi - lo;
    const frac = span > 0 ? clamp((cur - lo) / span, 0, 1) : 1;
    ui.zoomFill.style.width = `${frac * 100}%`;
    ui.knob.style.left = `${frac * 100}%`;
    ui.knob.setAttribute("aria-valuemin", String(lo));
    ui.knob.setAttribute("aria-valuemax", String(hi));
    ui.knob.setAttribute("aria-valuenow", String(cur));
    ui.knob.setAttribute("aria-valuetext", `${tr("m119")}${fmt(cur)}${tr("m120")}`);
    const seekable = span > 0 && typeof session.seek === "function" && !state.running;
    ui.zoom.classList.toggle("mb-dead", !seekable);
    ui.zoom.title = seekable
      ? `${tr("m121")}${fmt(lo)} – ${fmt(hi)}${tr("m122")}${fmt(span)}${tr("m123")}`
      : (state.running ? tr("m124") : tr("m125"));

    // marks carry an ADDRESS, not a step (§3.5), so they cannot be positioned
    // on a time axis. Listed as address chips instead of invented positions.
    clear(ui.marks);
    if (tl.marks && tl.marks.length) {
      ui.marks.appendChild(el("span", {
        style: { fontSize: "10.5px", color: "var(--mb-dim)" },
        title: tr("m126"),
        text: tr("m127"),
      }));
      for (const mk of tl.marks) {
        ui.marks.appendChild(el("button", {
          class: "mb-mk",
          style: { color: mk.kind === "watchpoint" ? "var(--mb-grn)" : "var(--mb-acc)" },
          text: `${mk.kind === "watchpoint" ? "◈" : "●"} ${pad5(mk.addr)}`,
          title: tr("m128"),
          onclick: () => jumpMemory(mk.addr),
        }));
      }
    }

    clear(ui.tlA); clear(ui.tlB); clear(ui.tlC);
    ui.tlA.append(fmt(lo), el("span", {
      style: { color: lost ? "var(--mb-amb)" : "var(--mb-ghost)" },
      text: lost ? `${tr("m129")}${fmt(span)}${tr("m130")}` : tr("m131"),
    }));
    ui.tlB.style.color = "var(--mb-mut)";
    ui.tlB.textContent = `▲ ${fmt(cur)}`;
    ui.tlC.textContent = `${fmt(tl.max_reached)}${tr("m132")}`;
  }

  function stepAtPointer(ev) {
    const s = state.snap;
    if (!s) return null;
    const [lo, hi] = s.timeline.seekable;
    if (hi <= lo) return null;
    const box = ui.zoom.getBoundingClientRect();
    const f = clamp((ev.clientX - box.left) / box.width, 0, 1);
    return Math.round(lo + f * (hi - lo));
  }

  /* --------------------------------------------------------- interaction */

  const listeners = [];
  const on = (target, type, fn, opts) => {
    target.addEventListener(type, fn, opts);
    listeners.push(() => target.removeEventListener(type, fn, opts));
  };

  ui.btnStep.onclick = () => call("step");
  ui.btnBack.onclick = () => call("back");
  ui.btnRun.onclick = () => {
    if (state.running) { call("stop"); return; }
    state.running = true; state.liveStep = null; state.stopReason = null;
    if (state.snap) { renderBar(state.snap); renderTimeline(state.snap); }
    if (!call("run", state.chunk)) { state.running = false; }
  };
  ui.btnChunk.onclick = () => {
    state.chunk = CHUNKS[(CHUNKS.indexOf(state.chunk) + 1) % CHUNKS.length];
    ui.btnChunk.textContent = `⏩ ×${fmt(state.chunk)}`;
  };
  ui.btnReset.onclick = () => {
    state.memOffset = 0; state.selected = null; state.stopReason = null;
    state.output = null;
    if (!call("reset") && typeof options.onReset === "function") options.onReset();
  };
  ui.explain.onclick = () => {
    if (typeof options.onExplain === "function") options.onExplain(state.snap);
  };

  // memory grid: hover tip, click to pin, shift-click to watch, wheel to scroll
  on(ui.grid, "mouseover", (ev) => {
    const cell = ev.target.closest(".mb-cell");
    if (!cell) return;
    state.hover = Number(cell.dataset.addr);
    showTip(state.hover, cell);
  });
  on(ui.grid, "mouseleave", () => { state.hover = null; hideTip(); });
  on(ui.grid, "click", (ev) => {
    const cell = ev.target.closest(".mb-cell");
    if (!cell) return;
    const addr = Number(cell.dataset.addr);
    if (ev.shiftKey) { call("watchpoint", addr, "toggle"); return; }
    state.selected = state.selected === addr ? null : addr;
    if (state.snap) renderMemory(state.snap);
  });
  on(ui.grid, "wheel", (ev) => {
    if (!state.snap) return;
    ev.preventDefault();
    const rows = ev.shiftKey ? MEM_ROWS : 1;
    state.memOffset += (ev.deltaY > 0 ? 1 : -1) * MEM_COLS * rows;
    hideTip();
    reSnapshot();
  }, { passive: false });

  // timeline: drag the knob / click the track, both clamped to `seekable`
  let dragId = null;
  const beginDrag = (ev) => {
    if (ui.zoom.classList.contains("mb-dead")) return;
    const step = stepAtPointer(ev);
    if (step == null) return;
    ev.preventDefault();          // otherwise the drag becomes a text selection
    dragId = ev.pointerId;
    state.dragging = true;
    ui.zoom.setPointerCapture(ev.pointerId);
    ui.zoomGhost.style.display = "block";
    moveDrag(ev);
  };
  const moveDrag = (ev) => {
    if (!state.dragging || ev.pointerId !== dragId) return;
    const step = stepAtPointer(ev);
    if (step == null) return;
    const box = ui.zoom.getBoundingClientRect();
    ui.zoomGhost.style.left = `${clamp(ev.clientX - box.left, 0, box.width)}px`;
    // Fire-and-forget: the knob itself only moves when a snapshot comes back,
    // so there is still exactly one path that changes displayed state.
    if (step !== state.lastSeek) { state.lastSeek = step; call("seek", step); }
  };
  const endDrag = (ev) => {
    if (!state.dragging) return;
    state.dragging = false; dragId = null; state.lastSeek = undefined;
    ui.zoomGhost.style.display = "none";
    try { ui.zoom.releasePointerCapture(ev.pointerId); } catch { /* already gone */ }
  };
  on(ui.zoom, "pointerdown", beginDrag);
  on(ui.zoom, "pointermove", moveDrag);
  on(ui.zoom, "pointerup", endDrag);
  on(ui.zoom, "pointercancel", endDrag);
  on(ui.ovLost, "click", (ev) => {
    ev.stopPropagation();
    showError(() => tr("m133"), "info");
  });
  on(ui.knob, "keydown", (ev) => {
    const s = state.snap;
    if (!s) return;
    const [lo, hi] = s.timeline.seekable;
    const span = hi - lo;
    if (span <= 0) return;
    const big = Math.max(1, Math.round(span / 20));
    const delta = { ArrowLeft: -1, ArrowRight: 1, PageDown: -big, PageUp: big }[ev.key];
    if (delta == null && ev.key !== "Home" && ev.key !== "End") return;
    ev.preventDefault();
    const target = ev.key === "Home" ? lo : ev.key === "End" ? hi
      : clamp(s.timeline.current + delta, lo, hi);
    call("seek", target);
  });

  // keyboard: the usual debugger keys
  on(frame, "keydown", (ev) => {
    if (ev.target.closest("input,textarea") || ev.target === ui.knob) return;
    if (ev.key === "ArrowRight" || ev.key === "F10") { ev.preventDefault(); ui.btnStep.click(); }
    else if (ev.key === "ArrowLeft") { ev.preventDefault(); ui.btnBack.click(); }
    else if (ev.key === "F5") { ev.preventDefault(); ui.btnRun.click(); }
    else if (ev.key === "Escape" && state.running) { ev.preventDefault(); call("stop"); }
  });
  frame.tabIndex = -1;

  /* ------------------------------------------------------------- inbound */

  /**
   * `severity` is this screen's own judgement, NOT the worker's `kind` -- that
   * field carries an error *class* (`ValueError`, `no_program`, `worker`), so
   * testing it against "error" silently downgraded every real failure to a
   * calm blue notice.
   */
  let errorMessage = null;
  let errorSeverity = "error";
  function showError(message, severity = "error") {
    errorMessage = message; errorSeverity = severity;
    clear(ui.err);
    ui.err.hidden = false;
    ui.err.style.background = severity === "error"
      ? "color-mix(in oklab,#8c2620 30%,transparent)"
      : "color-mix(in oklab,var(--mb-amb) 18%,transparent)";
    ui.err.style.borderColor = severity === "error" ? "#8c2620" : "var(--mb-amb)";
    ui.err.append(
      el("span", { text: severity === "error" ? "⚠" : "ℹ" }),
      el("span", { text: typeof message === "function" ? message() : message }),
      el("button", {
        style: { marginLeft: "auto", color: "inherit" }, text: "✕", 'aria-label': document.documentElement.lang === 'en' ? 'Dismiss message' : '关闭消息',
        onclick: () => { ui.err.hidden = true; },
      }));
  }

  function applySnapshot(data) {
    if (!data || !data.registers) return;
    state.snap = data;
    if (data.registers.terminated || !state.running) state.liveStep = null;
    render();
    if (data.memory && data.memory.count !== state.memCount) requestWindow();
    else windowRequested = true;
  }

  function applyProgress(payload) {
    const step = typeof payload === "number" ? payload : payload && payload.step;
    if (!Number.isFinite(step)) return;
    state.running = true;
    state.liveStep = step;
    if (!state.snap) { ui.stepNum.textContent = `${tr("m134")}${fmt(step)}`; return; }
    // `progress` carries a step and nothing else, so only the step-derived
    // chrome moves. Repainting 288 heat cells per progress tick would be both
    // wrong (the data is stale) and expensive.
    renderBar(state.snap);
    renderTimeline(state.snap);
  }

  function applyStopped(payload = {}) {
    state.running = false;
    state.liveStep = null;
    state.stopReason = payload.reason || null;
    if (payload.data) applySnapshot(payload.data);
    else if (state.snap) render();
  }

  function applyError(payload = {}) {
    state.running = false;
    state.liveStep = null;
    // `no_program` means a command reached the worker before `load` did. That
    // is a sequencing race between the shell and this screen, not a fact about
    // the program, and rendering it as a red banner would alarm the reader
    // about nothing. Clear the run state so nothing hangs, and say nothing.
    if (payload.kind !== "no_program") {
      showError(payload.message || (() => tr("m135")), "error");
    }
    if (state.snap) render();
  }

  /**
   * `registers.output_tail` is the text; `output_len` stays the true total
   * even when the tail is clipped, which is what lets the count say honestly
   * how much is off screen. The fallback chain below is for snapshots from an
   * older worker that predates the field -- those carry only a length, and the
   * panel says so rather than showing an empty terminal as if it were real
   * output. `setOutput()` overrides everything, for callers that hold the text
   * themselves.
   */
  function renderOutput(s) {
    const r = s.registers;
    const len = r.output_len;
    const text = state.output
      ?? (typeof r.output_tail === "string" ? r.output_tail : null)
      ?? (typeof s.output === "string" ? s.output : null)
      ?? (typeof r.output_text === "string" ? r.output_text : null);

    clear(ui.outBox);
    if (text == null) {
      ui.outCount.textContent = `${fmt(len)}${tr("m136")}`;
      ui.outBox.append(el("span", {
        style: { color: "var(--mb-dim)", fontSize: "12px",
                 fontFamily: "var(--mb-headFont)" },
        text: len
          ? `${tr("m137")}${fmt(len)}）`
          : tr("m138"),
      }));
      return;
    }

    ui.outCount.textContent = r.output_truncated
      ? `${tr("m139")}${fmt(text.length)}${tr("m140")}${fmt(len)}${tr("m141")}`
      : `${fmt(len)}${tr("m142")}`;
    ui.outCount.title = r.output_truncated
      ? `${tr("m143")}${fmt(len - text.length)}${tr("m144")}` : "";

    // The truncation notice lives in the header, not in the box: the box
    // auto-scrolls to the newest character, which would park any leading
    // notice permanently out of sight.
    ui.outBox.append(text, el("span", { class: "mb-caret" }));
    ui.outBox.scrollTop = ui.outBox.scrollHeight;
  }

  /* ---------------------------------------------------- session wiring */

  const offs = [onLocaleChange(() => {
    for (const update of bindings) update();
    // Dynamic panels read the current locale but never issue worker commands.
    // Keep keyboard focus on the equivalent address control after repaint.
    const active = document.activeElement;
    const addr = active?.closest('[data-addr]')?.dataset.addr;
    const wasGutter = active?.classList.contains('mb-gut');
    render();
    if (!ui.err.hidden) showError(errorMessage, errorSeverity);
    if (addr != null && !active.isConnected) {
      frame.querySelector('[data-addr="' + addr + '"]' + (wasGutter ? ' .mb-gut' : ''))?.focus();
    }
    if (state.hover != null) {
      const cell = ui.grid.querySelector('[data-addr="' + state.hover + '"]');
      if (cell) showTip(state.hover, cell);
    }
  })];
  if (typeof session.on === "function") {
    const sub = (name, fn) => {
      const off = session.on(name, fn);
      if (typeof off === "function") offs.push(off);
    };
    sub("snapshot", applySnapshot);
    sub("progress", applyProgress);
    sub("stopped", applyStopped);
    sub("error", applyError);
  }

  // If a snapshot already exists -- the caller loaded before mounting -- adopt
  // it now so the screen is never briefly blank. Otherwise wait: the `load`
  // that has not happened yet will produce one.
  if (session && session.lastSnapshot) applySnapshot(session.lastSnapshot);

  return {
    el: frame,
    state,
    applySnapshot, applyProgress, applyStopped, applyError,
    setOutput(text) { state.output = text; if (state.snap) renderOutput(state.snap); },
    setFileName(name) { state.fileName = name || ""; if (state.snap) renderBar(state.snap); },
    setTheme(name) {
      state.theme = name;
      applyTheme(frame, name);
      if (name === "light" && state.palette === "blackbody") state.palette = "paper";
      if (name === "dark" && state.palette === "paper") state.palette = "blackbody";
      frame.style.setProperty("--mb-heat-grad", HEAT_GRADIENTS[state.palette]);
      render();
    },
    setPalette(name) {
      if (!HEAT_GRADIENTS[name]) return;
      state.palette = name;
      frame.style.setProperty("--mb-heat-grad", HEAT_GRADIENTS[name]);
      if (state.snap) renderMemory(state.snap);
    },
    destroy() {
      for (const off of offs) { try { off(); } catch { /* ignore */ } }
      for (const off of listeners) off();
      clear(root);
    },
  };
}

export default mountDebugger;
