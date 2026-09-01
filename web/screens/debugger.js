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

function el(tag, attrs = {}, ...kids) {
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
  doc.head.appendChild(el("style", { id: "mb-debugger-css", text: CSS }));
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
    o.btnBack = el("button", { class: "mb-btn", title: "回退一步 (←)" }, "⏮ 回退");
    o.btnStep = el("button", { class: "mb-btn", title: "单步执行 (→)" }, "⏭ 单步");
    o.btnRun = el("button", { class: "mb-btn mb-primary", title: "继续 / 暂停 (F5)" }, "▶ 继续");
    o.btnChunk = el("button", {
      class: "mb-btn mb-quiet",
      title: "每个运行分块的步数。worker 在分块之间才检查停止请求，块越大越快、响应越钝。",
    });
    o.btnReset = el("button", { class: "mb-btn mb-quiet", title: "重置到第 0 步" }, "⟲ 重置");
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
        el("div", { class: "mb-ptitle", text: "反汇编" }), o.dsmNote),
      el("div", { class: "mb-dsm-cols" },
        el("span"), el("span", { text: "地址" }), el("span", { text: "字符" }),
        el("span", { text: "原值" }), el("span", { text: "助记符" }),
        el("span", { text: "效果" })),
      o.dsmList, o.dsmFoot);

    // ---- memory --------------------------------------------------------
    o.memRange = el("span", { class: "mb-tag" });
    o.memFollow = el("button", { class: "mb-tag mb-on", title: "把窗口拉回 D 附近" });
    o.memC = el("span", { class: "mb-tag" });
    o.rowLab = el("div", { class: "mb-rowlab" });
    o.grid = el("div", {
      class: "mb-grid", role: "grid",
      "aria-label": "内存写入热力图",
    });
    o.tip = el("div", { class: "mb-tip", hidden: true });
    o.peak = el("span", { class: "mb-lg-txt" });
    o.scaleBtn = el("button", {
      class: "mb-tag",
      title: "热度归一化方式。线性 = heat / heat_max（契约字面读法）；"
           + "对数 = log1p(heat)/log1p(heat_max)。真实程序里单格写入次数相差上千倍，"
           + "线性会把除最热一格外的所有格子压成纯黑。",
    });
    o.legendBar = el("div", { class: "mb-lg-bar" });
    o.selLine = el("div", { class: "mb-selline" });

    const memWrap = el("div", { class: "mb-memwrap" }, o.rowLab, o.grid, o.tip);
    const mem = el("div", { class: "mb-panel" },
      el("div", { class: "mb-phead" },
        el("div", { class: "mb-ptitle", text: "内存 · 写入热度" }),
        el("div", { class: "mb-pnote", style: { display: "flex", gap: "8px", alignItems: "center" } },
          o.memRange, o.memFollow, o.memC)),
      memWrap,
      el("div", { class: "mb-legend" },
        el("span", { class: "mb-lg-txt", text: "冷" }),
        o.legendBar,
        o.peak,
        o.scaleBtn,
        el("span", { class: "mb-chip" },
          el("i", { style: { boxShadow: "0 0 0 2px var(--mb-dRing) inset" } }), "D 指针"),
        el("span", { class: "mb-chip", style: { color: "var(--mb-acc)" } },
          el("i", { style: { boxShadow: "0 0 0 2px var(--mb-acc) inset" } }), "C 指针"),
        el("span", { class: "mb-chip", style: { color: "var(--mb-wRing)" } },
          el("i", { style: { boxShadow: "0 0 0 2px var(--mb-wRing) inset" } }), "本步写入")),
      o.selLine);

    // ---- right column --------------------------------------------------
    o.regs = el("div", { style: { display: "flex", flexDirection: "column", gap: "10px" } });
    o.prevList = el("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } });
    o.explain = el("button", {
      class: "mb-ptitle",
      style: { color: "var(--mb-amb)", letterSpacing: "0", fontSize: "11px" },
      text: "展开讲解 ↗",
    });
    o.bpList = el("div", {
      style: { display: "flex", flexDirection: "column", gap: "7px",
               overflowY: "auto", minHeight: "0" },
    });

    const right = el("div", { class: "mb-right" },
      el("div", { class: "mb-card" },
        el("div", { class: "mb-ptitle", style: { marginBottom: "10px" }, text: "寄存器" }),
        o.regs),
      el("div", { class: "mb-card" },
        el("div", { style: { display: "flex", justifyContent: "space-between",
                             alignItems: "center", marginBottom: "10px" } },
          el("span", { class: "mb-ptitle", text: "下一步预演" }), o.explain),
        o.prevList),
      el("div", { class: "mb-card mb-grow" },
        el("div", { class: "mb-ptitle", style: { marginBottom: "10px" }, text: "断点 · 监视点" }),
        o.bpList));

    // ---- timeline ------------------------------------------------------
    o.tlStat = el("div", { class: "mb-tl-stat" });
    o.tlHint = el("div", { class: "mb-tl-hint" });
    o.ovLost = el("div", { class: "mb-ov-lost", title: "这段历史已被丢弃，不可回溯" });
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
      "aria-label": "时间线位置（仅可回溯区间）",
    }, el("i"));
    o.zoom = el("div", { class: "mb-zoom" },
      el("div", { class: "mb-zoom-ticks" }), o.zoomFill, o.zoomGhost, o.knob);
    o.marks = el("div", { class: "mb-marks" });
    o.tlA = el("span"); o.tlB = el("span"); o.tlC = el("span");

    const tl = el("div", { class: "mb-tl" },
      el("div", { class: "mb-tl-head" },
        el("span", { class: "mb-ptitle", text: "时间线" }), o.tlStat, o.tlHint),
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
        el("span", { class: "mb-ptitle", text: "输出" }), o.outCount),
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
    ui.file.textContent = state.fileName || "(未命名)";
    ui.file.hidden = !state.fileName;

    const step = state.running && state.liveStep != null ? state.liveStep : r.step;
    ui.stepNum.textContent = `步 ${fmt(step)}`;

    // The 10,000-cap is not a snapshot field; when history has saturated it is
    // exactly the width of `seekable`, and before that there is no cap to show.
    const cap = tl.seekable[0] > 0 ? tl.seekable[1] - tl.seekable[0] : null;
    ui.stepSub.textContent =
      `历史 ${fmt(r.history_size)}${cap ? ` / ${fmt(cap)}` : ""}`
      + ` · 输入 ${fmt(r.input_consumed)}/${fmt(r.input_total)}`;

    const { text, tone } = statusPill(s);
    ui.pill.textContent = text;
    ui.pill.className = `mb-pill${tone ? ` mb-${tone}` : ""}`;

    ui.btnRun.textContent = state.running ? "⏸ 暂停" : "▶ 继续";
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
      ? "教学视图（设计稿 1b）在 v1 范围之外，尚未构建"
      : "打开教学视图";
  }

  function statusPill(s) {
    const r = s.registers;
    if (state.running) return { text: "▶ 运行中", tone: "live" };
    if (r.terminated) return { text: "■ 已终止", tone: "calm" };
    const reason = state.stopReason || r.stop_reason;
    if (reason === "breakpoint") {
      const bp = (s.breakpoints.breakpoints || []).find((b) => b.addr === r.c);
      return {
        text: `⏸ 断点 @${pad5(r.c)}${bp ? ` · 第 ${fmt(bp.hit_count)} 次` : ""}`,
        tone: "",
      };
    }
    if (reason === "watchpoint") return { text: `⏸ 监视点命中`, tone: "" };
    if (reason === "error") return { text: "⚠ 错误", tone: "" };
    if (reason === "input_exhausted") return { text: "⏸ 输入耗尽", tone: "" };
    // `stop_reason` is "running" whenever the debugger is not *stopped* for a
    // reason -- including after a plain step() -- so it is not evidence that
    // anything is executing. `state.running`, driven by run/stopped events, is.
    const label = reason === "running" ? "已暂停" : (STOP_REASON_TEXT[reason] || "已暂停");
    return { text: `⏸ ${label}`, tone: "calm" };
  }

  // ---- disassembly -----------------------------------------------------
  function renderDisasm(s) {
    const d = s.disasm, ops = opColors(state.theme);
    ui.dsmNote.textContent =
      `${pad5(d.window[0])}–${pad5(d.window[1])} · 跟随 C ◉`;
    // The contract gives DisasmView no scroll offset -- the window is always
    // centred on C -- so "跟随 C" is a statement of fact, not a toggle.
    ui.dsmNote.title = "反汇编窗口恒以 C 为中心（ViewModel 未提供偏移量），无法脱离跟随";

    clear(ui.dsmList);
    for (const r of d.rows) {
      const exec = !NON_EXEC.has(r.effect);
      const row = el("div", {
        class: `mb-dsm-row${r.is_current ? " mb-cur" : ""}`,
        "data-addr": r.addr,
      });
      row.appendChild(el("button", {
        class: `mb-gut${r.has_breakpoint ? " mb-has" : ""}`,
        title: r.has_breakpoint ? "移除断点" : "在此设置断点",
        "aria-label": `${r.has_breakpoint ? "移除" : "设置"}断点 ${pad5(r.addr)}`,
        text: r.is_current ? "▶" : (r.has_breakpoint ? "●" : ""),
        style: { color: r.has_breakpoint && !r.is_current ? "var(--mb-acc)" : "" },
        onclick: () => call("breakpoint", r.addr, "toggle"),
      }));
      row.appendChild(el("span", {
        class: "mb-dsm-addr", text: pad5(r.addr),
        title: "双击：把内存窗口移到此地址",
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
        text: EFFECT_TEXT[r.effect] || r.effect,
        title: r.opcode == null ? "" : `opcode (${r.raw} + ${r.addr}) % 94 = ${r.opcode}`,
        style: { color: r.is_current ? "var(--mb-sub)" : "var(--mb-dim)" },
      }));
      ui.dsmList.appendChild(row);
    }

    const cur = d.rows.find((r) => r.is_current);
    clear(ui.dsmFoot);
    ui.dsmFoot.append(
      "点击行首打点断点 · 双击地址跳到内存 · ",
      el("span", {
        style: { color: "var(--mb-amb)" },
        text: cur && s.teaching.encrypt
          ? `${JSON.stringify(cur.char)}+${s.teaching.encrypt.index} 执行后改写为 `
            + `${JSON.stringify(s.teaching.encrypt.new_char)}`
          : "当前指令不触发加密改写",
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
      ? "跟随 D" : `偏移 ${m.offset > 0 ? "+" : ""}${fmt(m.offset)}`;
    ui.memFollow.classList.toggle("mb-on", m.offset === 0);
    ui.memFollow.onclick = () => { state.memOffset = 0; reSnapshot(); };
    ui.memC.textContent = m.c < m.start ? `C=${pad5(m.c)} 窗外 ↖`
      : m.c > end ? `C=${pad5(m.c)} 窗外 ↘` : `C=${pad5(m.c)} 窗内`;

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
        "aria-label": `mem[${c.addr}] = ${c.value}，写入 ${c.heat} 次`,
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

    ui.peak.textContent = `热 · 峰值 ${fmt(m.heat_max)} 次`;
    ui.scaleBtn.textContent = state.heatScale === "log" ? "对数刻度" : "线性刻度";
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
        text: "点击任一格固定选中 · ⇧点击设/撤监视点 · 滚轮上下翻页",
      }));
      return;
    }
    const wp = (s.breakpoints.watchpoints || []).find((w) => w.addr === c.addr);
    ui.selLine.append(
      el("span", { style: { color: "var(--mb-faint)", fontSize: "11px" }, text: "已选" }),
      el("span", { style: { color: "var(--mb-tx)" }, text: `mem[${c.addr}]` }),
      el("span", { style: { color: "var(--mb-mut)" }, text: `= ${fmt(c.value)}` }),
      el("span", { style: { color: "var(--mb-dim)" }, text: charNote(c) }),
      el("span", { style: { color: "var(--mb-amb)" }, text: `写入 ${fmt(c.heat)} 次` }),
      wp ? el("span", { style: { color: "var(--mb-grn)" }, text: "◈ 已布设监视点" }) : null,
      el("span", {
        style: { marginLeft: "auto", color: c.is_d ? "var(--mb-cyn)" : "var(--mb-dim)" },
        text: c.is_d ? "= D" : `距 D ${c.addr - m.d >= 0 ? "+" : ""}${fmt(c.addr - m.d)}`,
      }));
  }

  const charNote = (c) => (c.char === "." ? "不可打印" : `${JSON.stringify(c.char)} 可打印`);

  function showTip(addr, cellEl) {
    const s = state.snap, c = cellAt(addr);
    if (!s || !c) return hideTip();
    const wp = (s.breakpoints.watchpoints || []).find((w) => w.addr === addr);
    clear(ui.tip);
    ui.tip.append(
      el("h4", { text: `mem[${c.addr}]` }),
      el("dl", {},
        el("dt", { text: "值" }),
        el("dd", { text: `${fmt(c.value)} · ${charNote(c)}` }),
        el("dt", { text: "写入" }),
        el("dd", { style: { color: "var(--mb-amb)" }, text: `${fmt(c.heat)} 次` }),
        el("dt", { text: "距 D" }),
        el("dd", {
          style: { color: "var(--mb-cyn)" },
          text: `${c.addr - s.memory.d >= 0 ? "+" : ""}${fmt(c.addr - s.memory.d)}`,
        }),
        el("dt", { text: "监视" }),
        el("dd", {
          style: { color: wp ? "var(--mb-grn)" : "var(--mb-dim)" },
          text: wp
            ? `✓ wp 已布设${wp.last_value == null ? "" : ` · 上次 ${fmt(wp.last_value)}`}`
            : "—",
        })),
      el("div", { class: "mb-tipfoot", text: "点击固定 · ⇧点击设监视点" }));

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
      ? (CHAR_KIND_TEXT[r.a_char_kind] || "")
      : `ASCII ${sym} ${CHAR_KIND_TEXT[r.a_char_kind] || ""}`;
    const rows = [
      { n: "A", color: "var(--mb-amb)", v: r.a, next: r.next_a, sub: aSub },
      { n: "C", color: "var(--mb-acc)", v: r.c, next: r.next_c, sub: "代码指针" },
      { n: "D", color: "var(--mb-cyn)", v: r.d, next: r.next_d, sub: "数据指针" },
    ];
    clear(ui.regs);
    for (const row of rows) {
      ui.regs.appendChild(el("div", { class: "mb-reg" },
        el("span", { class: "mb-n", style: { color: row.color }, text: row.n }),
        el("span", { class: "mb-v", text: fmt(row.v) }),
        el("span", {
          class: "mb-next",
          text: `→ ${row.next == null ? "—" : fmt(row.next)}`,
          title: row.next == null ? "下一步不改变该寄存器，或程序已终止" : "",
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
        text: t.terminated ? "程序已终止，没有下一步。" : "下一步没有可展示的副作用。",
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
    return { text: e.text, detail: was ? `原 ${was[1]}` : e.detail };
  }

  // ---- breakpoints / watchpoints ---------------------------------------
  function renderBreakpoints(s) {
    const b = s.breakpoints;
    clear(ui.bpList);
    const bps = b.breakpoints || [], wps = b.watchpoints || [];
    if (!bps.length && !wps.length) {
      ui.bpList.appendChild(el("div", {
        class: "mb-empty",
        text: "尚未设置。点击反汇编行首打断点，⇧点击内存格设监视点。",
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
          title: bp.enabled ? "停用" : "启用",
          onclick: () => call("breakpoint", bp.addr, bp.enabled ? "disable" : "enable"),
        }),
        el("button", {
          style: { color: "var(--mb-tx)", flex: "none" },
          text: pad5(bp.addr),
          title: "把内存窗口移到此地址",
          onclick: () => jumpMemory(bp.addr),
        }),
        el("span", { style: { color: "var(--mb-faint)" }, text: bp.mnemonic }),
        el("span", {
          class: "mb-bptag",
          text: bp.condition_text || (bp.temporary ? "临时" : ""),
          title: bp.condition_text ? "命中条件" : "",
        }),
        el("span", {
          class: "mb-bphits",
          text: bp.enabled ? `命中 ${fmt(bp.hit_count)}` : "已停用",
        }),
        el("button", {
          class: "mb-x", text: "✕", title: "删除断点",
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
          title: "把内存窗口移到此地址", onclick: () => jumpMemory(wp.addr),
        }),
        el("span", { style: { color: "var(--mb-faint)" }, text: "watch" }),
        el("span", {
          class: "mb-bptag",
          text: wp.last_value == null ? "" : `上次 ${fmt(wp.last_value)}`,
        }),
        el("span", { class: "mb-bphits", text: wp.enabled ? "启用" : "已停用" }),
        el("button", {
          class: "mb-x", text: "✕", title: "删除监视点",
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
      `全程 ${fmt(tl.max_reached)} 步 · 当前 ${fmt(cur)}`
      + ` · 已回溯 ${fmt(Math.max(0, tl.max_reached - tl.current))}`;
    ui.tlHint.textContent = lost
      ? "灰色区域历史已丢弃，不可拖拽 · 需要更早状态请重置后重新运行"
      : "全部历史仍在窗口内，整条时间线均可拖拽";
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
      ? (roomy ? `历史已丢弃 · 不可达 · ${fmt(lo)} 起可回溯 ▶` : `◀ 不可达 · ${fmt(lo)} 起`)
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
    ui.knob.setAttribute("aria-valuetext", `第 ${fmt(cur)} 步`);
    const seekable = span > 0 && typeof session.seek === "function" && !state.running;
    ui.zoom.classList.toggle("mb-dead", !seekable);
    ui.zoom.title = seekable
      ? `可拖拽区间 ${fmt(lo)} – ${fmt(hi)}（最近 ${fmt(span)} 步）`
      : (state.running ? "运行中不可拖拽" : "尚无可回溯的历史");

    // marks carry an ADDRESS, not a step (§3.5), so they cannot be positioned
    // on a time axis. Listed as address chips instead of invented positions.
    clear(ui.marks);
    if (tl.marks && tl.marks.length) {
      ui.marks.appendChild(el("span", {
        style: { fontSize: "10.5px", color: "var(--mb-dim)" },
        title: "ViewModel 的 marks 带的是内存地址而非步数，无法投影到时间轴上，故在此列出",
        text: "标记(地址)",
      }));
      for (const mk of tl.marks) {
        ui.marks.appendChild(el("button", {
          class: "mb-mk",
          style: { color: mk.kind === "watchpoint" ? "var(--mb-grn)" : "var(--mb-acc)" },
          text: `${mk.kind === "watchpoint" ? "◈" : "●"} ${pad5(mk.addr)}`,
          title: "把内存窗口移到此地址",
          onclick: () => jumpMemory(mk.addr),
        }));
      }
    }

    clear(ui.tlA); clear(ui.tlB); clear(ui.tlC);
    ui.tlA.append(fmt(lo), el("span", {
      style: { color: lost ? "var(--mb-amb)" : "var(--mb-ghost)" },
      text: lost ? ` · 可回溯区起点(最近 ${fmt(span)} 步)` : " · 全程可回溯",
    }));
    ui.tlB.style.color = "var(--mb-mut)";
    ui.tlB.textContent = `▲ ${fmt(cur)}`;
    ui.tlC.textContent = `${fmt(tl.max_reached)} · 最新 ▶`;
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
    showError("这段历史已被丢弃（后端只保留最近 10,000 步），无法回溯到这里。", "info");
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
  function showError(message, severity = "error") {
    clear(ui.err);
    ui.err.hidden = false;
    ui.err.style.background = severity === "error"
      ? "color-mix(in oklab,#8c2620 30%,transparent)"
      : "color-mix(in oklab,var(--mb-amb) 18%,transparent)";
    ui.err.style.borderColor = severity === "error" ? "#8c2620" : "var(--mb-amb)";
    ui.err.append(
      el("span", { text: severity === "error" ? "⚠" : "ℹ" }),
      el("span", { text: message }),
      el("button", {
        style: { marginLeft: "auto", color: "inherit" }, text: "✕",
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
    if (!state.snap) { ui.stepNum.textContent = `步 ${fmt(step)}`; return; }
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
      showError(payload.message || "未知错误", "error");
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
      ui.outCount.textContent = `${fmt(len)} 字符`;
      ui.outBox.append(el("span", {
        style: { color: "var(--mb-dim)", fontSize: "12px",
                 fontFamily: "var(--mb-headFont)" },
        text: len
          ? `快照未携带输出文本（只有 output_len = ${fmt(len)}）`
          : "尚无输出",
      }));
      return;
    }

    ui.outCount.textContent = r.output_truncated
      ? `显示最后 ${fmt(text.length)} / 共 ${fmt(len)} 字符`
      : `${fmt(len)} 字符`;
    ui.outCount.title = r.output_truncated
      ? `更早的 ${fmt(len - text.length)} 个字符不在快照里` : "";

    // The truncation notice lives in the header, not in the box: the box
    // auto-scrolls to the newest character, which would park any leading
    // notice permanently out of sight.
    ui.outBox.append(text, el("span", { class: "mb-caret" }));
    ui.outBox.scrollTop = ui.outBox.scrollHeight;
  }

  /* ---------------------------------------------------- session wiring */

  const offs = [];
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
