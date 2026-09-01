// Main-thread side of the web debugger: worker lifecycle, a promise-shaped
// command API, and an event bus for the messages nobody asked for.
//
// Contract: docs/design/tui-web-architecture.md §5.2. This file talks to
// worker.js and to nothing else Python-shaped -- by the time a screen module
// (screens/launch.js, screens/debugger.js) sees anything, it is a plain object
// that came through `json.dumps` in Python and `JSON.parse` in the worker.
//
// The API has two shapes because the protocol has two shapes:
//
//   await bridge.step()            commands that produce exactly one reply
//   bridge.on("progress", fn)      messages that arrive on their own schedule
//
// A run is both: `await bridge.run()` resolves at the `stopped` message, while
// `progress` and throttled `snapshot` events arrive throughout.

/** Message types the worker can send; every one is also an event bus topic. */
export const EVENTS = ["booting", "ready", "snapshot", "progress", "stopped", "error"];

/**
 * Correlation ids are an ADDITION to §5.2's tables, which give no way to tell
 * whose reply is whose. Without them a `seek` that fails and a `step` that
 * succeeds in flight together are indistinguishable to the caller, and a
 * `snapshot` pushed mid-run looks like the answer to whatever was last asked.
 * The worker echoes `id` on the reply it generated and omits it on anything
 * unsolicited, which is exactly the distinction the bus needs.
 */
let nextId = 1;

export class MalbolgeBridge {
  /**
   * @param {object} [opts]
   * @param {URL|string} [opts.workerUrl]  defaults to ./worker.js next to this module
   * @param {Worker} [opts.worker]         inject a pre-made worker (tests)
   */
  constructor({ workerUrl, worker } = {}) {
    this._listeners = new Map(EVENTS.map((e) => [e, new Set()]));
    this._pending = new Map();
    this._running = false;
    this._lastSnapshot = null;
    this._readyInfo = null;
    this._terminated = false;

    this._ready = new Promise((resolve, reject) => {
      this._resolveReady = resolve;
      this._rejectReady = reject;
    });
    // Nothing may await `ready` before it is handed out, so an early boot
    // failure would otherwise be an unhandled rejection in the console.
    this._ready.catch(() => {});

    this._worker =
      worker ??
      new Worker(workerUrl ?? new URL("./worker.js", import.meta.url), { type: "module" });

    this._worker.onmessage = (ev) => this._receive(ev.data);
    this._worker.onmessageerror = () =>
      this._receive({ type: "error", message: "worker message could not be deserialised", kind: "structured_clone" });
    this._worker.onerror = (ev) =>
      this._receive({ type: "error", message: ev?.message ?? "worker error", kind: "worker" });
  }

  // ---------------------------------------------------------------- state

  /** Resolves with the `ready` message once Pyodide has booted. */
  get ready() {
    return this._ready;
  }

  /** The `ready` payload, or null before boot finishes. */
  get readyInfo() {
    return this._readyInfo;
  }

  /** True between a `run` starting and its `stopped`. */
  get running() {
    return this._running;
  }

  /** The most recent snapshot seen, solicited or not. */
  get lastSnapshot() {
    return this._lastSnapshot;
  }

  // ---------------------------------------------------------------- events

  /** Subscribe. Returns an unsubscribe function. */
  on(type, fn) {
    const set = this._listeners.get(type);
    if (!set) throw new Error(`unknown event: ${type}`);
    set.add(fn);
    return () => set.delete(fn);
  }

  off(type, fn) {
    this._listeners.get(type)?.delete(fn);
  }

  /** Resolve on the next event of this type. */
  once(type) {
    return new Promise((resolve) => {
      const off = this.on(type, (msg) => {
        off();
        resolve(msg);
      });
    });
  }

  _emit(msg) {
    for (const fn of this._listeners.get(msg.type) ?? []) {
      try {
        fn(msg);
      } catch (err) {
        // A screen throwing in its handler must not take down the bus and
        // strand every other panel.
        console.error(`[bridge] listener for "${msg.type}" threw`, err);
      }
    }
  }

  // ---------------------------------------------------------------- receive

  _receive(msg) {
    if (!msg || typeof msg.type !== "string") return;

    switch (msg.type) {
      case "ready":
        this._readyInfo = msg;
        this._resolveReady(msg);
        break;

      case "snapshot":
        this._lastSnapshot = msg.data;
        this._settleById(msg.id, msg.data, null);
        break;

      case "stopped":
        this._running = false;
        if (msg.data) this._lastSnapshot = msg.data;
        // Every waiter on a stop resolves together: a `run` and the `stop`
        // that interrupted it are two promises answered by one message, and
        // only the run's id is echoed.
        this._settleAll("stopped", msg, null);
        break;

      case "error": {
        const err = new Error(msg.message);
        err.kind = msg.kind;
        if (msg.id !== undefined && this._pending.has(msg.id)) {
          this._settleById(msg.id, null, err);
        } else {
          // An unattributed error during a run is the run's failure; the run
          // will never produce its `stopped` otherwise.
          if (this._running) {
            this._running = false;
            this._settleAll("stopped", null, err);
          }
          this._rejectReady(err);
        }
        break;
      }

      default:
        break;
    }

    this._emit(msg);
  }

  _settleById(id, value, err) {
    if (id === undefined) return;
    const entry = this._pending.get(id);
    if (!entry) return;
    this._pending.delete(id);
    err ? entry.reject(err) : entry.resolve(value);
  }

  _settleAll(want, value, err) {
    for (const [id, entry] of [...this._pending]) {
      if (entry.want !== want) continue;
      this._pending.delete(id);
      err ? entry.reject(err) : entry.resolve(value);
    }
  }

  // ---------------------------------------------------------------- send

  _send(msg, want) {
    if (this._terminated) return Promise.reject(new Error("bridge terminated"));
    const id = nextId++;
    const promise = new Promise((resolve, reject) => {
      this._pending.set(id, { want, resolve, reject });
    });
    this._worker.postMessage({ ...msg, id });
    return promise;
  }

  // ---------------------------------------------------------------- commands
  //
  // Each of these resolves with the §3.7 snapshot the state change produced,
  // except run/stop which resolve with the `stopped` message.

  /** Build a debugger. `source` is Malbolge source text. */
  load(source, { input = "", memCount, disasmCount, variant } = {}) {
    return this._send({ type: "load", source, input, memCount, disasmCount, variant }, "snapshot");
  }

  step() {
    return this._send({ type: "step" }, "snapshot");
  }

  back() {
    return this._send({ type: "back" }, "snapshot");
  }

  /** Jump to `step` on the current timeline. Rejects (kind "seek") past max_step_reached. */
  seek(step) {
    return this._send({ type: "seek", step }, "snapshot");
  }

  reset() {
    return this._send({ type: "reset" }, "snapshot");
  }

  /**
   * Re-request a snapshot, optionally moving the memory/disasm windows. The
   * window options are sticky in the worker, so later automatic snapshots keep
   * whatever was last set here.
   */
  snapshot({ memOffset, memCount, disasmCount } = {}) {
    return this._send({ type: "snapshot", memOffset, memCount, disasmCount }, "snapshot");
  }

  /** action: "toggle" (add/remove) | "enable" | "disable" | "remove". */
  breakpoint(addr, action = "toggle", conditionText) {
    return this._send({ type: "breakpoint", addr, action, conditionText }, "snapshot");
  }

  /** action: "toggle" (add/remove) | "enable" | "disable" | "remove". */
  watchpoint(addr, action = "toggle") {
    return this._send({ type: "watchpoint", addr, action }, "snapshot");
  }

  /**
   * Run until a breakpoint, a watchpoint, termination, `maxSteps`, or `stop()`.
   * Resolves with the `stopped` message. `progress` and throttled `snapshot`
   * events arrive on the bus meanwhile.
   *
   * `maxSteps` is an addition to §5.2 -- it is what makes the `limit` stop
   * reason reachable, and gives a page a runaway guard that does not depend on
   * the user finding the stop button.
   */
  run({ chunk, maxSteps } = {}) {
    this._running = true;
    return this._send({ type: "run", chunk, maxSteps }, "stopped");
  }

  /** Ask the worker to stop between chunks. Resolves with the `stopped` message. */
  stop() {
    return this._send({ type: "stop" }, "stopped");
  }

  /** Kill the worker. The bridge is unusable afterwards. */
  terminate() {
    this._terminated = true;
    const err = new Error("bridge terminated");
    for (const [id, entry] of [...this._pending]) {
      this._pending.delete(id);
      entry.reject(err);
    }
    this._worker.terminate?.();
  }
}

// ------------------------------------------------------------------ session
//
// `createSession()` is the API the screens are written against, and its shape
// is fixed by the team contract, not by this file. Three properties of it are
// load-bearing:
//
//   1. Commands return nothing. Every state change comes back as a `snapshot`
//      event, so a screen has exactly one update path. If a command also
//      returned its result, a screen could render from either, and the two
//      diverge the moment a run is pushing throttled snapshots of its own.
//   2. `on()` returns an unsubscribe function, so a screen can unbind on exit.
//   3. `createSession()` does not resolve until the worker is `ready`, but
//      `onBoot` fires throughout — the launch screen has ~1.15 s of Pyodide
//      boot to narrate and must not show a blank frame.
//
// `MalbolgeBridge` underneath is the protocol-shaped object: promise-returning
// commands, events that are the worker's messages verbatim. It stays reachable
// as `session.raw` because that is the shape a test wants (smoke.mjs drives
// both), and because debugging the boundary is easier when you can await a
// single command. Screens should not use it.

/**
 * How a session handler is called. A screen wants the snapshot, not the
 * envelope carrying it; `progress` / `stopped` / `error` have no single payload
 * field, so those arrive as the message itself, whose fields are exactly what
 * the contract destructures ({step}, {reason, data}, {message, kind}).
 */
const _PAYLOAD_OF = { snapshot: (m) => m.data };

/**
 * A command's failure is already reported as an `error` event, so the promise
 * `MalbolgeBridge` returns is redundant here -- but dropping a rejecting
 * promise on the floor is an unhandledrejection, which in a browser is a
 * console error and, with some error reporters, a page-level alarm. Swallow it
 * explicitly: the event is the report.
 */
function fireAndForget(promise) {
  // NOT swallowing the error: it has already been reported, once, as an `error`
  // event on the bus, which is the only path a screen is allowed to read. What
  // is being discarded here is the second, redundant report.
  promise?.catch?.(() => {});
}

/**
 * Boot a worker and return the screen-facing session.
 *
 * @param {object} [opts]
 * @param {(phase: string) => void} [opts.onBoot]  each `booting` phase, during boot
 * @param {URL|string} [opts.workerUrl]
 * @param {Worker} [opts.worker]  inject a pre-made worker (tests)
 */
export async function createSession({ onBoot, workerUrl, worker } = {}) {
  const bridge = new MalbolgeBridge({ workerUrl, worker });
  if (onBoot) bridge.on("booting", (msg) => onBoot(msg.phase));
  await bridge.ready;

  let disposed = false;

  return {
    /** Subscribe. Returns the unsubscribe function. */
    on(type, fn) {
      const unwrap = _PAYLOAD_OF[type] ?? ((m) => m);
      return bridge.on(type, (msg) => fn(unwrap(msg), msg));
    },

    /**
     * Unsubscribe by handler. `on()` wraps the handler, so the bus holds the
     * wrapper and not what you passed -- use `on()`'s return value instead.
     * This is here for handlers registered directly on `raw`.
     */
    off: (type, fn) => bridge.off(type, fn),

    // Commands. All return undefined; watch the events.
    load(source, input = "", opts = {}) { fireAndForget(bridge.load(source, { input, ...opts })); },
    step() { fireAndForget(bridge.step()); },
    back() { fireAndForget(bridge.back()); },
    run(opts) { fireAndForget(bridge.run(opts)); },
    stop() { fireAndForget(bridge.stop()); },
    seek(step) { fireAndForget(bridge.seek(step)); },
    reset() { fireAndForget(bridge.reset()); },
    snapshot(opts) { fireAndForget(bridge.snapshot(opts)); },
    breakpoint(addr, action, conditionText) {
      fireAndForget(bridge.breakpoint(addr, action, conditionText));
    },
    watchpoint(addr, action) { fireAndForget(bridge.watchpoint(addr, action)); },

    /** Boolean, not a promise: by the time you hold a session, boot is done. */
    get ready() { return !disposed && bridge.readyInfo !== null; },

    /** Terminate the worker. The session is unusable afterwards. */
    dispose() {
      disposed = true;
      bridge.terminate();
    },

    get running() { return bridge.running; },
    get lastSnapshot() { return bridge.lastSnapshot; },
    get readyInfo() { return bridge.readyInfo; },

    /** The promise-shaped bridge underneath. For tests and boundary debugging. */
    raw: bridge,
  };
}

// ------------------------------------------------------------------ vendor
//
// The two self-hosted files a launch screen needs. They live here rather than
// in screens/launch.js so that only one module knows the vendor/ layout that
// build.mjs produces.

/** Resolve a path inside web/vendor/ relative to this module. */
export function vendorURL(path) {
  return new URL(`./vendor/${path}`, import.meta.url);
}

/** Build metadata written by build.mjs: {wheel, version, pyodideVersion, variant, builtAt}. */
export async function fetchBuildInfo() {
  const res = await fetch(vendorURL("build.json"));
  if (!res.ok) throw new Error(`vendor/build.json -> ${res.status} (run \`node web/build.mjs\`)`);
  return res.json();
}

/** examples/manifest.json: the example catalogue, with step counts and expected output. */
export async function fetchManifest() {
  const res = await fetch(vendorURL("manifest.json"));
  if (!res.ok) throw new Error(`vendor/manifest.json -> ${res.status} (run \`node web/build.mjs\`)`);
  return res.json();
}

/** Source text of one example, named by a manifest entry's `file`. */
export async function fetchExample(file) {
  const res = await fetch(vendorURL(`examples/${file}`));
  if (!res.ok) throw new Error(`vendor/examples/${file} -> ${res.status}`);
  return res.text();
}

export default MalbolgeBridge;
