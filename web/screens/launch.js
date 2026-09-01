// web/screens/launch.js — canvas 1d, the "stranger's first click" screen:
// pick an example / paste code / drop a file.
//
// Every color, spacing and font-size value below is copied verbatim from
// docs/design/web-ui-canvas/Malbolge Web.dc.html, id="1d" (source lines
// ~734-769) and its dark token group `T` in renderVals() at the end of that
// file. The one deliberate structural deviation from the canvas: 1d is drawn
// there as a fixed 1440x860 "device frame" so it sits side-by-side with the
// other six screens on one pan/zoom canvas. Here it *is* the real first
// screen of the app, so the outer frame is full-viewport instead of a fixed
// box — the values inside it (margins, gaps, font sizes, colors) are
// untouched.
//
// This module never imports bridge.js. index.html owns the session and
// passes this module a plain `onLoad(source, input)` callback plus a
// `setBootPhase` handle it can call as boot progress comes in. That keeps
// the pure logic below (pickFeaturedExamples / formatCells / formatSteps /
// formatCost / renderLaunchHTML) testable with plain Node — no DOM, no
// bridge.js required.

// Measured, not assumed: docs/design/tui-web-architecture.md §5.2
// ("execution … 177,000 steps/s").
export const STEPS_PER_SEC = 177_000;

// Design tokens live in web/theme.js as `--mb-*` CSS custom properties,
// applied to <html> by index.html's `applyTheme(document.documentElement,
// "dark")` before this screen ever mounts. This module reads them via
// `var(--mb-<token>, <literal>)` rather than importing theme.js directly, so
// it stays DOM/import-free — the pure functions above (and below) run under
// plain Node with no bridge.js, no theme.js, no browser. The fallback in each
// var() is the literal DARK value, so rendering is identical whether or not
// applyTheme has run yet; it's the same pattern the design canvas itself uses
// for --acc.
const T = {
  pn: "var(--mb-pn, #14121a)",
  // Launch-screen tokens; added to theme.js after this screen was written.
  dropBg: "var(--mb-dropBg, #12101a)",
  cardHoverBg: "var(--mb-cardHoverBg, #171422)",
  tagline: "var(--mb-tagline, #a79fc0)",
  err: "var(--mb-err, #ff8c7a)",
  pnBd: "var(--mb-pnBd, #262331)",
  bd: "var(--mb-bd, #2a2735)",
  ghost: "var(--mb-ghost, #4d4860)",
  logo2: "var(--mb-logo2, #5a5470)",
  dim: "var(--mb-dim, #6f6a80)",
  cyn: "var(--mb-cyn, #7fe3ef)",
  mut: "var(--mb-mut, #8b8798)",
  sub: "var(--mb-sub, #cfc9e0)",
  tx: "var(--mb-tx, #e9e6f2)",
  acc: "var(--mb-acc, #ff5c38)",
  amb: "var(--mb-amb, #ffb454)",
  accTx: "var(--mb-accTx, #160a08)",
  tipBd: "var(--mb-tipBd, #3a3450)",
};

// Not yet in theme.js's DARK set (flagged to team-lead to add; kept literal
// rather than force-fitting an existing token with the wrong semantics):
//   dropBg      #12101a  drop-zone panel background (deliberately darker than `pn`)
//   cardHoverBg #171422  example-card hover background
//   tagline     #a79fc0  hero subtitle color
//   err         #ff8c7a  inline error-banner text (distinct from OP_COLORS.dark.end,
//                        which happens to share this hex for an unrelated mnemonic)

// Curated roles for the three featured cards, each with a fallback chain
// rather than a single hardcoded filename — the numbers shown always come
// from the manifest, and if a preferred file ever disappears from it the
// card quietly falls back to the next candidate instead of breaking.
//
//   入门 (intro)     — the cheapest way to see ENCRYPT self-rewriting happen.
//   长循环 (long run) — big enough to make the timeline/heatmap worth using.
//                       quine.mal is even bigger (~6.5 min, see formatCost)
//                       and is deliberately NOT the first choice — it only
//                       surfaces if 99bottles.mal is ever removed.
//   带输入 (input)    — needs stdin, so it's worth practicing breakpoints on.
//                       truth.mal is preferred over cat/cat2 because its
//                       3,836 steps give a breakpoint something to land on;
//                       cat2.mal's 33 steps do not.
const FEATURED_ROLES = [
  {
    label: "入门",
    desc: "经典 Hello, World —— 观察加密改写最直观的一步",
    candidates: ["hello.mal"],
  },
  {
    label: "长循环",
    desc: "步数很多,适合看时间线拖拽和内存热力图,但要等得起",
    candidates: ["99bottles.mal", "quine.mal"],
  },
  {
    label: "带输入",
    desc: "需要标准输入,适合练断点与监视点",
    candidates: ["truth.mal", "cat.mal", "cat2.mal"],
  },
];

export function formatCells(n) {
  return `${n.toLocaleString("en-US")} 单元`;
}

export function formatSteps(n) {
  if (n < 10_000) return `${n.toLocaleString("en-US")} 步`;
  if (n < 1_000_000) return `≈ ${(n / 1000).toFixed(1)} 千步`;
  return `≈ ${Math.round(n / 10_000).toLocaleString("en-US")} 万步`;
}

/** null when the run is fast enough that a cost line would just be noise. */
export function formatCost(steps) {
  const seconds = steps / STEPS_PER_SEC;
  if (seconds < 1.5) return null;
  if (seconds < 90) return `预计运行 ≈ ${Math.round(seconds)} 秒`;
  return `预计运行 ≈ ${(seconds / 60).toFixed(1)} 分钟`;
}

/** Pure: manifest in, card view-models out. No DOM, easy to unit test. */
export function pickFeaturedExamples(manifest) {
  const byFile = new Map((manifest?.programs ?? []).map((p) => [p.file, p]));
  const cards = [];
  for (const role of FEATURED_ROLES) {
    const file = role.candidates.find((f) => byFile.has(f));
    if (!file) continue;
    const prog = byFile.get(file);
    cards.push({
      file: prog.file,
      label: role.label,
      desc: role.desc,
      cellsText: formatCells(prog.cells),
      stepsText: formatSteps(prog.steps),
      costText: formatCost(prog.steps),
      readsInput: !!prog.reads_input,
    });
  }
  return cards;
}

function escapeHtml(s) {
  return String(s).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}

// The bridge's actual "booting" phase sequence (per web-worker: vendor reads
// vendor/build.json for the wheel name + Pyodide version, then pyodide/wheel/
// import). Measured: pyodide alone is ~1.1s of the ~1.15s boot, the other
// three phases together are ~45ms — so in practice this indicator spends
// nearly all its time showing the "pyodide" label. "ready" is not one of the
// bridge's phases; it's this module's own sentinel (set by index.html once
// createSession() resolves) for "boot finished, hide the indicator".
const BOOT_LABELS = {
  vendor: "读取版本信息…",
  pyodide: "Pyodide 运行时加载中…",
  wheel: "解包 pyMalbolge…",
  import: "初始化 Python 环境…",
  ready: "就绪",
};

function cardHtml(ex) {
  return `
    <div class="mb-card" data-example="${escapeHtml(ex.file)}" tabindex="0" role="button"
         aria-label="载入示例 ${escapeHtml(ex.file)}"
         style="width:240px;padding:18px 20px;border-radius:12px;background:${T.pn};border:1px solid ${T.pnBd};cursor:pointer">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <span style="font-family:'IBM Plex Mono',monospace;font-size:14px;font-weight:600;color:${T.tx}">${escapeHtml(ex.file)}</span>
        <span style="font-size:10px;padding:1px 7px;border-radius:999px;border:1px solid ${T.bd};color:${T.mut}">${escapeHtml(ex.label)}</span>
      </div>
      <div style="font-size:12px;color:${T.mut};margin-top:6px;line-height:1.5">${escapeHtml(ex.desc)}</div>
      <div style="display:flex;gap:10px;margin-top:12px;font-family:'IBM Plex Mono',monospace;font-size:10.5px;color:${T.dim}">
        <span>${escapeHtml(ex.cellsText)}</span><span style="color:${T.amb}">${escapeHtml(ex.stepsText)}</span>
        ${ex.readsInput ? `<span style="color:${T.cyn}">需输入</span>` : ""}
      </div>
      ${ex.costText ? `<div style="margin-top:6px;font-family:'IBM Plex Mono',monospace;font-size:10.5px;color:${T.amb}">⏱ ${escapeHtml(ex.costText)}</div>` : ""}
    </div>`;
}

/** Pure: examples + boot phase in, full-screen HTML string out. */
export function renderLaunchHTML({ examples, bootPhase }) {
  const cardsHtml = examples.map(cardHtml).join("");
  const bootHtml =
    bootPhase && bootPhase !== "ready"
      ? `<div class="mb-boot" role="status" aria-live="polite">
           <span class="mb-boot-dot"></span>
           <span>${escapeHtml(BOOT_LABELS[bootPhase] ?? bootPhase)}</span>
         </div>`
      : "";

  return `
  <div class="mb-launch">
    <div style="display:flex;flex-direction:column;align-items:center;margin-top:84px;padding:0 24px;text-align:center">
      <div style="display:flex;gap:5px;align-items:flex-end;height:34px">
        <div style="width:8px;height:34px;border-radius:3px;background:linear-gradient(180deg,${T.amb},${T.acc})"></div>
        <div style="width:8px;height:16px;border-radius:3px;background:${T.logo2}"></div>
        <div style="width:8px;height:25px;border-radius:3px;background:${T.amb}"></div>
      </div>
      <div style="font-size:34px;font-weight:700;letter-spacing:.01em;margin-top:16px">pyMalbolge</div>
      <div style="font-size:15px;color:${T.tagline};margin-top:6px">Malbolge 调试器 —— 一门每走一步都会自我改写的语言,现在可以单步看清它</div>
      <div style="display:flex;gap:8px;margin-top:14px;font-size:11.5px;color:${T.dim};flex-wrap:wrap;justify-content:center">
        <span style="padding:3px 10px;border-radius:999px;border:1px solid ${T.bd};background:color-mix(in srgb, ${T.pn} 80%, transparent)">纯静态 · 无服务器</span>
        <span style="padding:3px 10px;border-radius:999px;border:1px solid ${T.bd};background:color-mix(in srgb, ${T.pn} 80%, transparent)">Python 跑在 Web Worker</span>
        <span style="padding:3px 10px;border-radius:999px;border:1px solid ${T.bd};background:color-mix(in srgb, ${T.pn} 80%, transparent)">代码不离开浏览器</span>
      </div>
    </div>

    <div style="display:flex;gap:16px;margin-top:52px;flex-wrap:wrap;justify-content:center;padding:0 24px">${cardsHtml}</div>

    <div class="mb-drop" style="width:764px;max-width:calc(100vw - 48px);box-sizing:border-box;margin-top:20px;border-radius:12px;border:1.5px dashed ${T.tipBd};background:color-mix(in srgb, ${T.dropBg} 80%, transparent);padding:26px;text-align:center">
      <div style="font-size:14px;color:${T.sub}">拖入 <span style="font-family:'IBM Plex Mono',monospace;color:${T.amb}">.mal</span> 文件,或把代码粘贴到这里</div>
      <textarea class="mb-paste" spellcheck="false" aria-label="粘贴 Malbolge 代码"
        style="display:block;width:100%;box-sizing:border-box;min-height:64px;margin-top:12px;resize:vertical;background:transparent;border:none;outline:none;font-family:'IBM Plex Mono',monospace;font-size:12px;color:${T.tx};text-align:left"
        placeholder="(=&lt;\`#9]~6ZY32Vx/4Rs+0No-&amp;Jk)&quot;Fh}|Bcy?\`=*z]Kw%oG4UUS0/@-ejc(:'8dc"></textarea>
      <div style="display:flex;justify-content:center;gap:14px;align-items:center;margin-top:16px;flex-wrap:wrap">
        <div class="mb-load-btn" role="button" tabindex="0" style="padding:9px 26px;border-radius:9px;background:${T.acc};color:${T.accTx};font-size:14px;font-weight:600;cursor:pointer">载入并调试</div>
        <span style="font-size:11.5px;color:${T.dim}">仅可打印 ASCII;空白字符会被忽略</span>
      </div>
      <div class="mb-drop-error" style="display:none;margin-top:10px;font-size:11.5px;color:${T.err}"></div>
    </div>

    ${bootHtml}

    <div style="margin-top:auto;padding:18px;display:flex;gap:8px;align-items:center;font-size:11.5px;color:${T.logo2};text-align:center;max-width:640px">
      <span style="width:7px;height:7px;border-radius:50%;background:${T.amb};animation:pulse 1.6s infinite;flex-shrink:0"></span>
      <span>首次加载约 10 MB(Pyodide 解释器),之后离线可用 · v1 仅支持原始 Malbolge:3¹⁰ = 59,049 个内存单元</span>
    </div>
  </div>`;
}

let stylesInjected = false;
function injectStyles(doc) {
  if (stylesInjected) return;
  stylesInjected = true;
  const style = doc.createElement("style");
  style.textContent = `
    .mb-launch { display:flex; flex-direction:column; align-items:center; min-height:100%; width:100%; padding-bottom:24px; box-sizing:border-box; }
    @keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:.45 } }
    .mb-card { transition: border-color .15s, background .15s; }
    .mb-card:hover, .mb-card:focus-visible { border-color: color-mix(in oklab, ${T.acc} 55%, ${T.pnBd}); background:${T.cardHoverBg}; outline:none; }
    .mb-drop { transition: border-color .15s; }
    .mb-drop:hover, .mb-drop.mb-drop-active { border-color: ${T.acc}; }
    .mb-load-btn:hover, .mb-load-btn:focus-visible { filter: brightness(1.08); outline:none; }
    .mb-paste::placeholder { color: ${T.ghost}; }
    .mb-boot { display:flex; gap:8px; align-items:center; font-size:11.5px; color:${T.mut}; margin-top:18px; }
    .mb-boot-dot { width:7px; height:7px; border-radius:50%; background:${T.amb}; animation: mb-boot-pulse 1.2s infinite; flex-shrink:0; }
    @keyframes mb-boot-pulse { 0%,100% { opacity:1 } 50% { opacity:.35 } }
  `;
  doc.head.appendChild(style);
}

/**
 * Mount the 1d launch screen into `container`.
 *
 * @param {HTMLElement} container
 * @param {object} [opts]
 * @param {string} [opts.manifestUrl] defaults to ./vendor/manifest.json next to this module
 * @param {(file: string) => string} [opts.exampleSourceUrl] defaults to ./vendor/examples/<file>
 * @param {() => Promise<any>} [opts.fetchManifest] override for testing/staging without a server
 * @param {(source: string, input: string) => void} [opts.onLoad]
 * @param {string} [opts.bootPhase] initial phase shown before the first setBootPhase() call
 * @returns {Promise<{ setBootPhase(phase: string): void }>}
 */
export async function mountLaunch(container, opts = {}) {
  const doc = container.ownerDocument ?? document;
  const {
    manifestUrl = new URL("../vendor/manifest.json", import.meta.url).href,
    exampleSourceUrl = (file) => new URL(`../vendor/examples/${file}`, import.meta.url).href,
    fetchManifest = () =>
      fetch(manifestUrl).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      }),
    onLoad = () => {},
    bootPhase = "pyodide",
  } = opts;

  injectStyles(doc);

  let examples = [];
  let manifestError = null;
  try {
    examples = pickFeaturedExamples(await fetchManifest());
  } catch (err) {
    manifestError = err;
  }

  container.innerHTML = renderLaunchHTML({ examples, bootPhase });

  const dropEl = container.querySelector(".mb-drop");
  const textarea = container.querySelector(".mb-paste");
  const loadBtn = container.querySelector(".mb-load-btn");
  const errorEl = container.querySelector(".mb-drop-error");

  function showError(msg) {
    if (!errorEl) return;
    errorEl.textContent = msg;
    errorEl.style.display = "block";
  }
  function clearError() {
    if (!errorEl) return;
    errorEl.style.display = "none";
  }

  if (manifestError) {
    showError(`示例列表加载失败(${manifestError.message}),仍可手动粘贴代码运行。`);
  }

  function submit(source) {
    if (!source || !source.trim()) {
      showError("还没有代码 —— 拖入文件、粘贴代码,或点一张示例卡片。");
      return;
    }
    clearError();
    onLoad(source, "");
  }

  loadBtn?.addEventListener("click", () => submit(textarea.value));
  loadBtn?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      submit(textarea.value);
    }
  });

  container.querySelectorAll(".mb-card").forEach((card) => {
    const activate = async () => {
      const file = card.dataset.example;
      clearError();
      try {
        const res = await fetch(exampleSourceUrl(file));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const source = await res.text();
        textarea.value = source;
        onLoad(source, "");
      } catch (err) {
        showError(
          `未能加载示例 ${file}(${err.message})—— 构建脚本可能还没有把 examples/ 复制到 web/vendor/examples/。`,
        );
      }
    };
    card.addEventListener("click", activate);
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        activate();
      }
    });
  });

  if (dropEl) {
    ["dragenter", "dragover"].forEach((evt) =>
      dropEl.addEventListener(evt, (e) => {
        e.preventDefault();
        dropEl.classList.add("mb-drop-active");
      }),
    );
    ["dragleave", "drop"].forEach((evt) =>
      dropEl.addEventListener(evt, (e) => {
        e.preventDefault();
        dropEl.classList.remove("mb-drop-active");
      }),
    );
    dropEl.addEventListener("drop", async (e) => {
      const file = e.dataTransfer?.files?.[0];
      if (!file) return;
      try {
        const source = await file.text();
        textarea.value = source;
        submit(source);
      } catch (err) {
        showError(`文件读取失败:${err.message}`);
      }
    });
  }

  return {
    setBootPhase(phase) {
      const existing = container.querySelector(".mb-boot");
      if (phase === "ready") {
        existing?.remove();
        return;
      }
      const label = escapeHtml(BOOT_LABELS[phase] ?? phase);
      if (existing) {
        existing.querySelector("span:last-child").textContent = BOOT_LABELS[phase] ?? phase;
        return;
      }
      const el = doc.createElement("div");
      el.className = "mb-boot";
      el.setAttribute("role", "status");
      el.setAttribute("aria-live", "polite");
      el.innerHTML = `<span class="mb-boot-dot"></span><span>${label}</span>`;
      container.querySelector(".mb-launch")?.appendChild(el);
    },
  };
}
