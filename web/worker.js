// Pyodide host. The ONLY place in the web build that touches Python.
//
// Contract: docs/design/tui-web-architecture.md §5.2 ("Worker protocol"),
// which is normative in both directions. Read that table first; this file
// implements it and the comments here only explain the parts the table
// cannot state -- chiefly why the run loop is shaped the way it is.
//
// Two invariants this file exists to hold:
//
//   1. No PyProxy ever leaves the worker. Pyodide hands out exactly one proxy
//      here -- `_mw_call`, a Python function -- and it takes a JSON string and
//      returns a JSON string. Everything the main thread receives came out of
//      `json.dumps` on the Python side and through `JSON.parse` on this side,
//      so it is a plain object by construction. That is the runtime half of
//      the architecture doc's Rule 2.
//
//   2. `stop` is honoured mid-run. A Worker has no preemption: `onmessage`
//      only fires when the event loop is idle, so a synchronous
//      `for (chunk of run_chunked())` would never see the stop message no
//      matter how many chunks it broke the work into. The loop below is
//      `async` and awaits a real macrotask between chunks precisely so the
//      queued `stop` gets a chance to run. See yieldToEventLoop().
//
// The module has two entry points: `createEngine()` (pure, injectable,
// what smoke.mjs drives under Node) and a worker-scope bootstrap at the
// bottom that wires it to `self.postMessage` / `self.onmessage`. Keeping the
// engine free of `self` is what makes the protocol testable without a browser.

// ---------------------------------------------------------------- constants

/** Fallback when vendor/build.json is missing or does not name a version. */
export const FALLBACK_PYODIDE_VERSION = "314.0.6";

/** §5.2's default; ~28 ms of work at the measured 177k steps/s. */
export const DEFAULT_CHUNK = 5000;

// Throttles for the two things sent *during* a run.
//
// `progress` at 10 Hz: a step counter updated faster than this is not
// readable, and slower than this stops looking live. The payload is ~60 bytes.
//
// `snapshot` at 2 Hz: the measured snapshot is 32 KB / 0.24 ms, so 2 Hz costs
// 64 KB/s of postMessage and 0.05% of a core -- nothing. The alternative
// bounds are what make this the interesting number: one snapshot per chunk
// would be ~35 Hz and 1.1 MB/s, which is the saturation the architecture doc
// warns about; no snapshot at all until `stopped` leaves the registers and
// heat map frozen for the 78 seconds 99bottles takes, so the page looks hung
// while it is in fact working. 2 Hz is the slowest rate that still reads as
// "the machine is moving", which is the whole job of a mid-run snapshot.
export const PROGRESS_INTERVAL_MS = 100;
export const SNAPSHOT_INTERVAL_MS = 500;

/** Where the wheel is unpacked inside the Pyodide filesystem. */
const SITE_DIR = "/home/pyodide/site";

// ---------------------------------------------------------------- python

// Everything Python-facing, as one string. It lives here rather than in the
// package because the worker's needs are worker-shaped (JSON in, JSON out,
// a generator held across calls) and because malbolge/ must stay a library
// that knows nothing about this build.
const PY_GLUE = `
import json

from malbolge.debugger import MalbolgeDebugger
from malbolge.view import build_snapshot


class _MwError(Exception):
    """An error with a protocol 'kind' attached, so worker.js can classify it
    without matching on message text."""

    def __init__(self, message, kind):
        super().__init__(message)
        self.kind = kind


class _WorkerSession:
    """The whole Python side of the web debugger, behind one JSON door.

    View options (mem_offset / mem_count / disasm_count) are sticky: a UI that
    scrolls the memory panel and then steps expects the panel to stay where it
    was put, and the worker is the only place that remembers.
    """

    def __init__(self):
        self.dbg = None
        self.gen = None
        self.source = ""
        self.input = ""
        self.mem_offset = 0
        self.mem_count = 24
        self.disasm_count = 11

    # ---- helpers ----------------------------------------------------

    def _require(self):
        if self.dbg is None:
            raise _MwError("no program loaded", "no_program")
        return self.dbg

    def _absorb_view_opts(self, args):
        if args.get("memOffset") is not None:
            self.mem_offset = int(args["memOffset"])
        if args.get("memCount") is not None:
            self.mem_count = max(1, int(args["memCount"]))
        if args.get("disasmCount") is not None:
            self.disasm_count = max(1, int(args["disasmCount"]))

    def _snapshot(self):
        return build_snapshot(
            self._require(),
            mem_offset=self.mem_offset,
            mem_count=self.mem_count,
            disasm_count=self.disasm_count,
        )

    def _status(self, state=None):
        dbg = self._require()
        if state is None:
            state = dbg.get_state()
        return {
            "step": state.step_count,
            "stopReason": state.stop_reason.value,
            "terminated": dbg.is_terminated,
        }

    # ---- ops --------------------------------------------------------

    def op_load(self, args):
        source = args.get("source") or ""
        input_data = args.get("input") or ""
        variant = args.get("variant") or "original"
        if variant != "original":
            # §5.2 v1 scope: Malbolge20's 3.48e9-cell sparse memory has not had
            # its browser-heap behaviour measured, so it is refused rather than
            # half-promised.
            raise _MwError(
                "web v1 supports original Malbolge only (got variant=" + str(variant) + ")",
                "unsupported_variant",
            )
        try:
            dbg = MalbolgeDebugger(source, input_data)
        except ValueError as exc:
            raise _MwError(str(exc), "load")
        self.dbg = dbg
        self.gen = None
        self.source = source
        self.input = input_data
        return {
            "sourceLength": dbg.source_length,
            "memorySize": dbg.config.memory_size,
            "inputLength": len(input_data),
        }

    def op_snapshot(self, args):
        self._absorb_view_opts(args)
        return self._snapshot()

    def op_step(self, args):
        dbg = self._require()
        self.gen = None
        return self._status(dbg.step())

    def op_back(self, args):
        dbg = self._require()
        self.gen = None
        state = dbg.step_back()
        status = self._status(state)
        status["atStart"] = state is None
        return status

    def op_seek(self, args):
        dbg = self._require()
        self.gen = None
        if args.get("step") is None:
            raise _MwError("seek requires a 'step' field", "protocol")
        try:
            state = dbg.seek(int(args["step"]))
        except ValueError as exc:
            # §5.2: past max_step_reached (or off the back of the 10k history
            # window) the backend raises; that is an 'error' message, not a
            # dead worker.
            raise _MwError(str(exc), "seek")
        return self._status(state)

    def op_reset(self, args):
        dbg = self._require()
        self.gen = None
        dbg.reset()
        return self._status()

    def op_breakpoint(self, args):
        dbg = self._require()
        addr = int(args.get("addr"))
        action = args.get("action") or "toggle"
        text = args.get("conditionText")
        existing = {bp.address: bp for bp in dbg.list_breakpoints()}
        # NOTE the naming trap: MalbolgeDebugger.toggle_breakpoint() flips the
        # *enabled* flag of an existing breakpoint. The protocol's 'toggle' is
        # the gutter click -- create it if absent, remove it if present --
        # which is why this does not call that method. 'enable'/'disable' are
        # the ones that map onto the enabled flag.
        if action == "toggle":
            if addr in existing:
                dbg.remove_breakpoint(addr)
                present = False
            else:
                dbg.add_breakpoint(addr, condition_text=text)
                present = True
        elif action in ("enable", "disable"):
            if addr not in existing:
                if action == "disable":
                    raise _MwError("no breakpoint at " + str(addr), "not_found")
                dbg.add_breakpoint(addr, condition_text=text)
                existing = {bp.address: bp for bp in dbg.list_breakpoints()}
            existing[addr].enabled = (action == "enable")
            present = True
        elif action == "remove":
            dbg.remove_breakpoint(addr)
            present = False
        else:
            raise _MwError("unknown breakpoint action: " + str(action), "protocol")
        return {"addr": addr, "action": action, "present": present}

    def op_watchpoint(self, args):
        dbg = self._require()
        addr = int(args.get("addr"))
        action = args.get("action") or "toggle"
        # list_watchpoints() returns the live Watchpoint objects, so mutating
        # .enabled here is the enable/disable the debugger has no method for.
        existing = {wp.address: wp for wp in dbg.list_watchpoints()}
        if action == "toggle":
            if addr in existing:
                dbg.remove_watchpoint(addr)
                present = False
            else:
                dbg.add_watchpoint(addr)
                present = True
        elif action in ("enable", "disable"):
            if addr not in existing:
                if action == "disable":
                    raise _MwError("no watchpoint at " + str(addr), "not_found")
                dbg.add_watchpoint(addr)
                existing = {wp.address: wp for wp in dbg.list_watchpoints()}
            existing[addr].enabled = (action == "enable")
            present = True
        elif action == "remove":
            dbg.remove_watchpoint(addr)
            present = False
        else:
            raise _MwError("unknown watchpoint action: " + str(action), "protocol")
        return {"addr": addr, "action": action, "present": present}

    # ---- the run generator ------------------------------------------
    #
    # run_chunked() is a Python generator, and it has to survive across
    # JS-side awaits: worker.js pulls one chunk per call and yields to the
    # event loop in between. Holding it on the session (rather than
    # iterating it from JS) keeps the generator object -- and therefore any
    # PyProxy of it -- entirely inside Python.

    def op_run_start(self, args):
        dbg = self._require()
        chunk = int(args.get("chunk") or 5000)
        if chunk <= 0:
            raise _MwError("chunk must be positive, got " + str(chunk), "protocol")
        self.gen = dbg.run_chunked(chunk)
        return {"step": dbg.step_count, "chunk": chunk}

    def op_run_chunk(self, args):
        dbg = self._require()
        if self.gen is None:
            return {"done": True, "step": dbg.step_count,
                    "stopReason": "stopped", "terminated": dbg.is_terminated}
        try:
            state = next(self.gen)
        except StopIteration:
            self.gen = None
            return {"done": True, "step": dbg.step_count,
                    "stopReason": "stopped", "terminated": dbg.is_terminated}
        reason = state.stop_reason.value
        # _run_iter yields get_state() mid-run, whose stop_reason is 'running'
        # right up until the last yield -- which carries the real reason
        # (terminated / breakpoint / watchpoint). So a non-'running' reason IS
        # the stop, one next() earlier than waiting for StopIteration.
        done = reason != "running"
        if done:
            self.gen = None
        return {"done": done, "step": state.step_count,
                "stopReason": reason, "terminated": dbg.is_terminated}

    def op_run_abort(self, args):
        # Dropping the generator is the documented way to stop: run_chunked()
        # guarantees the debugger is left on a clean instruction boundary and
        # that step()/run()/step_back() keep working afterwards.
        self.gen = None
        return self._status()


_mw_session = _WorkerSession()


def _mw_call(op, args_json):
    """The single door. JSON string in, JSON string out, no proxies either way."""
    try:
        args = json.loads(args_json) if args_json else {}
        handler = getattr(_mw_session, "op_" + op, None)
        if handler is None:
            return json.dumps({"error": {"message": "unknown op: " + str(op),
                                         "kind": "protocol", "op": op}})
        # json.dumps of the result is inside the try on purpose: it is where
        # Rule 2 gets enforced at runtime. A ViewModel that leaked an Enum or
        # a callable surfaces as an 'error' message, not as a broken worker.
        return json.dumps({"result": handler(args)})
    except _MwError as exc:
        return json.dumps({"error": {"message": str(exc), "kind": exc.kind, "op": op}})
    except Exception as exc:
        return json.dumps({"error": {
            "message": type(exc).__name__ + ": " + str(exc),
            "kind": "python", "op": op}})
`;

// ---------------------------------------------------------------- utilities

const textDecoder = new TextDecoder();

/**
 * Hand the event loop a real turn, so a queued `stop` (or any other message)
 * can be delivered before the next chunk starts.
 *
 * `await Promise.resolve()` would NOT do -- microtasks drain before the event
 * loop looks at the task queues at all, so a microtask-only yield spins
 * forever without ever running `onmessage`. It has to be a macrotask.
 *
 * Which macrotask is a trade-off. `setTimeout(0)` is unambiguously fair (the
 * timer task source is not the message task source, so the message is always
 * eligible) but is clamped -- 1 ms, and 4 ms once the nesting level passes 5,
 * which a chunk loop reaches immediately. Against a 28 ms chunk that is a 14%
 * tax. A MessageChannel ping is unclamped and, because browsers put it on the
 * same posted-message task source as `worker.postMessage`, lands *behind* any
 * pending `stop` -- ideal.
 *
 * So: MessageChannel by default, `setTimeout` every 8th yield. The timer is
 * the belt-and-braces bound -- if some engine ever did prefer its own channel
 * over incoming messages, stop latency is still capped at 8 chunks (~220 ms)
 * instead of unbounded, and the average cost stays near zero.
 */
function makeYielder() {
  let n = 0;
  let channel = null;
  let pending = null;

  const ensureChannel = () => {
    if (channel || typeof MessageChannel === "undefined") return channel;
    channel = new MessageChannel();
    channel.port1.onmessage = () => {
      const resolve = pending;
      pending = null;
      if (resolve) resolve();
    };
    return channel;
  };

  const yieldToEventLoop = () => {
    n += 1;
    const ch = n % 8 === 0 ? null : ensureChannel();
    if (!ch) return new Promise((resolve) => setTimeout(resolve, 0));
    return new Promise((resolve) => {
      pending = resolve;
      ch.port2.postMessage(0);
    });
  };

  // Node's MessagePort keeps the event loop alive; a long-lived channel would
  // stop `node smoke.mjs` from ever exiting. Closing it after each run is
  // cheaper than reasoning about unref() semantics per runtime.
  const dispose = () => {
    if (channel) {
      channel.port1.close();
      channel.port2.close();
      channel = null;
      pending = null;
    }
  };

  return { yieldToEventLoop, dispose };
}

// ---------------------------------------------------------------- engine

/**
 * Build the worker engine.
 *
 * @param {object} opts
 * @param {(msg: object) => void} opts.post            emit a worker->main message
 * @param {(o: object) => Promise<any>} opts.loadPyodide  receives {indexURL}
 * @param {(name: string) => Promise<Uint8Array>} opts.readVendor  read web/vendor/<name>
 * @param {string} [opts.pyodideIndexURL]  override the CDN URL entirely
 * @param {() => number} [opts.now]
 * @returns {{dispatch: (msg: object) => void, booted: Promise<object>}}
 */
export function createEngine({
  post,
  loadPyodide,
  readVendor,
  pyodideIndexURL = null,
  now = () => performance.now(),
}) {
  let py = null;
  let pyCall = null; // the one and only PyProxy
  let buildInfo = null;
  let loaded = false;

  let running = false;
  let stopRequested = false;
  let chain = Promise.resolve();

  const { yieldToEventLoop, dispose: disposeYielder } = makeYielder();

  // ---- python bridge ----

  /** Call into Python. Throws a tagged Error on the Python-side error envelope. */
  function call(op, args) {
    const raw = pyCall(op, JSON.stringify(args ?? {}));
    const parsed = JSON.parse(raw);
    if (parsed.error) {
      const err = new Error(parsed.error.message);
      err.kind = parsed.error.kind;
      err.op = parsed.error.op;
      throw err;
    }
    return parsed.result;
  }

  function postError(message, kind, id) {
    post({ type: "error", message: String(message), kind: kind ?? "internal", ...(id ? { id } : {}) });
  }

  function postSnapshot(args, id) {
    post({ type: "snapshot", data: call("snapshot", args ?? {}), ...(id ? { id } : {}) });
  }

  // ---- boot ----

  const booted = (async () => {
    const t0 = now();
    post({ type: "booting", phase: "vendor" });
    buildInfo = JSON.parse(textDecoder.decode(await readVendor("build.json")));

    post({ type: "booting", phase: "pyodide" });
    const version = buildInfo.pyodideVersion || FALLBACK_PYODIDE_VERSION;
    const indexURL = pyodideIndexURL ?? `https://cdn.jsdelivr.net/pyodide/v${version}/full/`;
    const t1 = now();
    py = await loadPyodide({ indexURL });
    const pyodideMs = Math.round(now() - t1);

    post({ type: "booting", phase: "wheel" });
    const t2 = now();
    py.unpackArchive(await readVendor(buildInfo.wheel), "zip", { extractDir: SITE_DIR });

    post({ type: "booting", phase: "import" });
    py.runPython(`import sys\nif ${JSON.stringify(SITE_DIR)} not in sys.path:\n    sys.path.insert(0, ${JSON.stringify(SITE_DIR)})`);
    py.runPython(PY_GLUE);
    pyCall = py.globals.get("_mw_call");
    const importMs = Math.round(now() - t2);

    const info = {
      type: "ready",
      pyodideMs,
      importMs,
      totalMs: Math.round(now() - t0),
      version: buildInfo.version,
      pyodideVersion: version,
    };
    post(info);
    return info;
  })();

  booted.catch((err) => postError(err?.message ?? err, "boot"));

  // ---- the run loop ----

  async function doRun(msg) {
    const chunk = msg.chunk ?? DEFAULT_CHUNK;
    // maxSteps is an addition to §5.2's `run` fields. It is what makes the
    // table's `limit` stop reason reachable at all -- nothing else in the
    // protocol can produce one -- and a browser tab wants a runaway guard
    // that does not depend on the user finding the stop button.
    const maxSteps = msg.maxSteps ?? null;

    call("run_start", { chunk });
    running = true;
    stopRequested = false;

    const t0 = now();
    let lastProgress = 0;      // 0 => first progress goes out immediately
    let lastSnapshot = t0;     // but the first 32 KB snapshot waits one interval
    let reason = "stopped";

    try {
      for (;;) {
        const r = call("run_chunk", {});
        if (r.done) {
          reason = r.stopReason;
          break;
        }
        if (stopRequested) {
          call("run_abort", {});
          reason = "stopped";
          break;
        }
        if (maxSteps !== null && r.step >= maxSteps) {
          call("run_abort", {});
          reason = "limit";
          break;
        }

        const t = now();
        if (t - lastProgress >= PROGRESS_INTERVAL_MS) {
          lastProgress = t;
          post({
            type: "progress",
            step: r.step,
            running: true,
            elapsedMs: Math.round(t - t0),
            stepsPerSecond: Math.round(r.step / Math.max(1e-6, (t - t0) / 1000)),
          });
        }
        if (t - lastSnapshot >= SNAPSHOT_INTERVAL_MS) {
          lastSnapshot = t;
          postSnapshot();
        }

        // The point of the whole exercise: without this, `stop` is undeliverable.
        await yieldToEventLoop();
      }
    } finally {
      running = false;
      stopRequested = false;
      disposeYielder();
    }

    post({ type: "stopped", reason, data: call("snapshot", {}), ...(msg.id ? { id: msg.id } : {}) });
  }

  // ---- command handlers ----

  const handlers = {
    load: (m) => {
      call("load", { source: m.source, input: m.input, variant: m.variant });
      loaded = true;
      postSnapshot({ memOffset: m.memOffset, memCount: m.memCount, disasmCount: m.disasmCount }, m.id);
    },
    step: (m) => { call("step", {}); postSnapshot(undefined, m.id); },
    back: (m) => { call("back", {}); postSnapshot(undefined, m.id); },
    seek: (m) => { call("seek", { step: m.step }); postSnapshot(undefined, m.id); },
    reset: (m) => { call("reset", {}); postSnapshot(undefined, m.id); },
    snapshot: (m) => postSnapshot({ memOffset: m.memOffset, memCount: m.memCount, disasmCount: m.disasmCount }, m.id),
    breakpoint: (m) => {
      call("breakpoint", { addr: m.addr, action: m.action, conditionText: m.conditionText });
      postSnapshot(undefined, m.id);
    },
    watchpoint: (m) => {
      call("watchpoint", { addr: m.addr, action: m.action });
      postSnapshot(undefined, m.id);
    },
    run: (m) => doRun(m),
  };

  /**
   * Handle one main->worker message.
   *
   * `stop` deliberately bypasses the queue: it is the one command whose whole
   * purpose is to interrupt the command that is already running, so putting it
   * behind that command in a serial chain would make it a no-op.
   */
  function dispatch(msg) {
    if (!msg || typeof msg.type !== "string") {
      postError("message with no type", "protocol");
      return;
    }
    if (msg.type === "stop") {
      if (running) {
        stopRequested = true;
        return;
      }
      // A stop with nothing running is a no-op, not an error: the outcome it
      // asks for is already true. It still ANSWERS, so a caller awaiting
      // `stopped` is never left hanging.
      //
      // Specifically not an error when nothing is loaded either, because the
      // two sides disagree about "running" for a window. `stop` is the one
      // command that skips the queue -- that is what makes it able to interrupt
      // a run -- while `bridge.js` flips its own `running` the moment `run` is
      // POSTED and this worker flips its own only when `doRun` actually starts,
      // which is after everything queued ahead of it. So a UI that correctly
      // guards its stop button on `running` can still deliver a stop while this
      // side is not running and possibly not even loaded: click a program, hit
      // run, hit stop, all inside the load. Erroring there reports "no program
      // loaded" about a program that is in fact loading. Every other command
      // queues, and those DO report it, because there the request really cannot
      // be carried out.
      post({
        type: "stopped",
        reason: "stopped",
        data: loaded ? call("snapshot", {}) : null,
        ...(msg.id ? { id: msg.id } : {}),
      });
      return;
    }

    const handler = handlers[msg.type];
    if (!handler) {
      postError(`unknown message type: ${msg.type}`, "protocol", msg.id);
      return;
    }

    chain = chain.then(async () => {
      try {
        await booted;
        await handler(msg);
      } catch (err) {
        postError(err?.message ?? err, err?.kind ?? "internal", msg.id);
      }
    });
  }

  return { dispatch, booted };
}

// ---------------------------------------------------------------- bootstrap

function isWorkerScope() {
  return (
    typeof self !== "undefined" &&
    typeof WorkerGlobalScope !== "undefined" &&
    self instanceof WorkerGlobalScope
  );
}

if (isWorkerScope()) {
  const engine = createEngine({
    post: (msg) => self.postMessage(msg),
    loadPyodide: async ({ indexURL }) => {
      const mod = await import(/* @vite-ignore */ `${indexURL}pyodide.mjs`);
      return mod.loadPyodide({ indexURL });
    },
    readVendor: async (name) => {
      const url = new URL(`./vendor/${name}`, self.location.href);
      const res = await fetch(url);
      if (!res.ok) throw new Error(`GET ${url.pathname} -> ${res.status}`);
      return new Uint8Array(await res.arrayBuffer());
    },
  });
  self.onmessage = (ev) => engine.dispatch(ev.data);
}
