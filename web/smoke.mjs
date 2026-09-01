#!/usr/bin/env node
// Node smoke test for worker.js. No browser, no bundler.
//
// `createEngine()` is the whole worker minus `self`, so this drives the real
// protocol -- the same Pyodide, the same wheel out of web/vendor/, the same
// PY_GLUE, the same chunked run loop. What it cannot test is the browser's
// event loop; what it can test is that the loop yields at all, which is the
// property `stop` depends on.
//
//   node build.mjs && node smoke.mjs
//
// Exits non-zero on the first failure.

import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadPyodide } from "pyodide";

import { createEngine, DEFAULT_CHUNK } from "./worker.js";
import { MalbolgeBridge, createSession } from "./bridge.js";

const WEB = dirname(fileURLToPath(import.meta.url));
const VENDOR = join(WEB, "vendor");

// ------------------------------------------------------------------ harness

let failures = 0;
let checks = 0;

function ok(cond, label, detail = "") {
  checks += 1;
  if (cond) {
    console.log(`  ok   ${label}${detail ? `   ${detail}` : ""}`);
  } else {
    failures += 1;
    console.log(`  FAIL ${label}${detail ? `   ${detail}` : ""}`);
  }
}

function eq(actual, expected, label) {
  ok(actual === expected, label, `got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)}`);
}

function section(name) {
  console.log(`\n== ${name}`);
}

// ------------------------------------------------------------------ engine

const messages = [];

/**
 * Every message the worker would postMessage. Two assertions ride on the
 * collector rather than on any individual test:
 *
 *   - structuredClone succeeds. That is literally what postMessage does, so a
 *     PyProxy or any other unclonable object leaking out of the worker fails
 *     here rather than in a browser.
 *   - JSON round-trip is identity. Stronger than clonability and the actual
 *     Rule 2 claim: what crosses the boundary is plain data.
 */
function post(msg) {
  try {
    structuredClone(msg);
  } catch (err) {
    failures += 1;
    console.log(`  FAIL structuredClone(${msg.type}) threw: ${err.message}`);
  }
  if (JSON.stringify(JSON.parse(JSON.stringify(msg))) !== JSON.stringify(msg)) {
    failures += 1;
    console.log(`  FAIL ${msg.type} is not JSON-identical after a round trip`);
  }
  messages.push(msg);
  for (const w of [...waiters]) {
    if (w.match(msg)) {
      waiters.delete(w);
      w.resolve(msg);
    }
  }
}

const waiters = new Set();

/** Resolve on the next message matching `match`; reject on `error` or timeout. */
function waitFor(match, { timeoutMs = 240000, label = "message" } = {}) {
  return new Promise((resolve, reject) => {
    const w = {
      match: (m) => {
        if (match(m)) return true;
        if (m.type === "error") {
          waiters.delete(w);
          clearTimeout(timer);
          reject(Object.assign(new Error(m.message), { kind: m.kind }));
        }
        return false;
      },
      resolve: (m) => {
        clearTimeout(timer);
        resolve(m);
      },
    };
    const timer = setTimeout(() => {
      waiters.delete(w);
      reject(new Error(`timed out waiting for ${label}`));
    }, timeoutMs);
    waiters.add(w);
  });
}

const ofType = (type) => (m) => m.type === type;

/** Poll until `cond` holds. The session API reports through events, not
 *  promises, so a test of it waits on observed state rather than on a return
 *  value -- which is the point of the contract. */
async function waitForEvent(cond, label, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  while (!cond()) {
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${label}`);
    await new Promise((r) => setTimeout(r, 5));
  }
}

const engine = createEngine({
  post,
  // The Node pyodide package ships its own runtime files; indexURL is the CDN
  // path the browser needs and is meaningless here.
  loadPyodide: () => loadPyodide(),
  readVendor: async (name) => new Uint8Array(await readFile(join(VENDOR, name))),
});

const send = (msg) => engine.dispatch(msg);

const readExample = (file) => readFile(join(VENDOR, "examples", file), "utf8");

// ------------------------------------------------------------------ tests

const t0 = Date.now();

section("boot");
const ready = await waitFor(ofType("ready"), { label: "ready" });
const phases = messages.filter((m) => m.type === "booting").map((m) => m.phase);
ok(phases.join(",") === "vendor,pyodide,wheel,import", "booting phases in order", phases.join(","));
ok(ready.pyodideMs > 0, "ready.pyodideMs", `${ready.pyodideMs} ms`);
ok(ready.importMs > 0, "ready.importMs", `${ready.importMs} ms (wheel unpack + import)`);
console.log(`  ---  malbolge ${ready.version} on pyodide ${ready.pyodideVersion}, boot ${ready.totalMs} ms`);

section("load + snapshot shape");
const hello = await readExample("hello.mal");
send({ type: "load", source: hello, memCount: 288 });
let snap = (await waitFor(ofType("snapshot"), { label: "load snapshot" })).data;
eq(Object.keys(snap).sort().join(","),
   "breakpoints,disasm,memory,registers,teaching,timeline",
   "snapshot has the six §3.7 ViewModels");
eq(snap.registers.step, 0, "registers.step at load");
eq(snap.memory.cells.length, 288, "memCount honoured");
ok(typeof snap.registers.stop_reason === "string", "stop_reason is a str, not an Enum", snap.registers.stop_reason);
ok(snap.breakpoints.breakpoints.every((b) => typeof b.has_condition === "boolean"),
   "breakpoints expose has_condition, not the predicate");
const snapBytes = JSON.stringify(snap).length;
console.log(`  ---  snapshot ${snapBytes} bytes at mem_count=288`);

section("step / back / seek");
for (let i = 0; i < 5; i += 1) {
  send({ type: "step" });
  snap = (await waitFor(ofType("snapshot"), { label: `step ${i + 1}` })).data;
}
eq(snap.registers.step, 5, "five steps");
const cAt5 = snap.registers.c;

send({ type: "back" });
snap = (await waitFor(ofType("snapshot"), { label: "back" })).data;
eq(snap.registers.step, 4, "back to step 4");

// seek is bounded by max_step_reached in BOTH directions -- it replays a
// timeline that has already been walked, it does not run new work. So the
// forward seek below is only legal because five steps were taken above.
send({ type: "seek", step: 1 });
snap = (await waitFor(ofType("snapshot"), { label: "seek 1" })).data;
eq(snap.registers.step, 1, "seek backward to 1");
eq(snap.timeline.current, 1, "timeline.current tracks the seek");
eq(snap.timeline.max_reached, 5, "timeline.max_reached remembers the high-water mark");

send({ type: "seek", step: 5 });
snap = (await waitFor(ofType("snapshot"), { label: "seek 5" })).data;
eq(snap.registers.step, 5, "seek forward again, back up to max_step_reached");

// §5.2: past max_step_reached the backend raises ValueError; that must arrive
// as an `error` message with the worker still alive.
send({ type: "seek", step: 10_000_000, id: "seek-too-far" });
const seekErr = await waitFor((m) => m.type === "error" && m.id === "seek-too-far",
                              { label: "seek error" }).catch((e) => e);
const seekErrMsg = messages.find((m) => m.type === "error" && m.id === "seek-too-far");
eq(seekErrMsg?.kind, "seek", "over-long seek -> error kind 'seek'");
ok(/beyond max_step_reached/.test(seekErrMsg?.message ?? ""), "error carries the backend's message",
   JSON.stringify(seekErrMsg?.message));
void seekErr;

send({ type: "step" });
snap = (await waitFor(ofType("snapshot"), { label: "step after failed seek" })).data;
eq(snap.registers.step, 6, "worker still alive after the error");

section("breakpoints");
send({ type: "breakpoint", addr: cAt5, action: "toggle" });
snap = (await waitFor(ofType("snapshot"), { label: "bp add" })).data;
eq(snap.breakpoints.breakpoints.length, 1, "toggle adds a breakpoint");
eq(snap.breakpoints.breakpoints[0].addr, cAt5, "at the requested address");
send({ type: "breakpoint", addr: cAt5, action: "disable" });
snap = (await waitFor(ofType("snapshot"), { label: "bp disable" })).data;
eq(snap.breakpoints.breakpoints[0].enabled, false, "disable clears the enabled flag");
send({ type: "breakpoint", addr: cAt5, action: "enable" });
await waitFor(ofType("snapshot"), { label: "bp enable" });

send({ type: "reset" });
snap = (await waitFor(ofType("snapshot"), { label: "reset" })).data;
eq(snap.registers.step, 0, "reset rewinds to step 0");
eq(snap.breakpoints.breakpoints.length, 1, "reset keeps breakpoints");

section("run to a breakpoint");
send({ type: "run" });
let stopped = await waitFor(ofType("stopped"), { label: "stopped at breakpoint" });
eq(stopped.reason, "breakpoint", "run stops at the breakpoint");
eq(stopped.data.registers.c, cAt5, "stopped where the breakpoint is");

section("run to termination");
send({ type: "breakpoint", addr: cAt5, action: "toggle" });
await waitFor(ofType("snapshot"), { label: "bp remove" });
send({ type: "reset" });
await waitFor(ofType("snapshot"), { label: "reset before full run" });
send({ type: "run" });
stopped = await waitFor(ofType("stopped"), { label: "stopped terminated" });
eq(stopped.reason, "terminated", "hello.mal terminates");
eq(stopped.data.registers.step, 39, "39 steps, as examples/manifest.json says");
eq(stopped.data.registers.output_len, 12, "12 characters of output ('Hello World!')");
eq(stopped.data.registers.terminated, true, "terminated flag set");

// -------------------------------------------------------------- the stop test
//
// The one test that is evidence rather than description. 99bottles.mal is
// 13,802,605 steps (~78 s at the measured 177k steps/s). If the run loop did
// not yield to the event loop between chunks, the `stop` dispatched from a
// timer below could not be delivered until the whole program had finished, and
// this would stop at 13.8M steps roughly 78 seconds from now.

section("stop mid-run (99bottles.mal, 13,802,605 steps)");
const bottles = await readExample("99bottles.mal");
const TOTAL_STEPS = 13_802_605;
const STOP_AFTER_MS = 1200;   // long enough that the snapshot throttle (500 ms) fires

send({ type: "load", source: bottles, memCount: 288 });
await waitFor(ofType("snapshot"), { label: "load 99bottles" });

const progressSeen = [];
const collectProgress = { match: (m) => { if (m.type === "progress") progressSeen.push(m); return false; }, resolve() {} };
waiters.add(collectProgress);

const runStart = Date.now();
const messagesBeforeRun = messages.length;
send({ type: "run", chunk: DEFAULT_CHUNK });

let stopSentAt = 0;
const stopTimer = setTimeout(() => {
  stopSentAt = Date.now();
  send({ type: "stop" });
}, STOP_AFTER_MS);

stopped = await waitFor(ofType("stopped"), { label: "stopped by request" });
clearTimeout(stopTimer);
waiters.delete(collectProgress);

const stopLatency = Date.now() - stopSentAt;
const stoppedAtStep = stopped.data.registers.step;
const elapsed = Date.now() - runStart;

eq(stopped.reason, "stopped", "stop reason is 'stopped'");
eq(stopped.data.registers.terminated, false, "the program did NOT run to the end");
ok(stoppedAtStep > 0, "some work happened before the stop", `${stoppedAtStep.toLocaleString()} steps`);
ok(stoppedAtStep < TOTAL_STEPS / 10, "stopped far short of the 13.8M total",
   `${stoppedAtStep.toLocaleString()} steps = ${(100 * stoppedAtStep / TOTAL_STEPS).toFixed(2)}% of the program`);
ok(elapsed < 15000, "and did it in well under the ~78 s a full run takes", `${elapsed} ms wall`);
ok(stopLatency < 2000, "stop honoured promptly after the message", `${stopLatency} ms from stop to stopped`);
ok(progressSeen.length >= 2, "progress messages arrived during the run",
   `${progressSeen.length} progress @ ~${(1000 * progressSeen.length / elapsed).toFixed(1)} Hz`);
ok(progressSeen.every((m) => m.running === true), "progress carries running: true");
// The throttle is the other half of the design: chunks arrive at ~35 Hz, and
// pushing a 29 KB snapshot at each of them is the postMessage saturation §5.2
// warns about. Mid-run snapshots must track the 500 ms interval, not the chunk
// rate.
const midRunSnapshots = messages.slice(messagesBeforeRun).filter((m) => m.type === "snapshot").length;
const chunksRun = stoppedAtStep / DEFAULT_CHUNK;
ok(midRunSnapshots <= Math.ceil(elapsed / 500) + 1,
   "mid-run snapshots follow the 500 ms throttle, not the chunk rate",
   `${midRunSnapshots} snapshots over ${elapsed} ms, against ${chunksRun} chunks`);
console.log(`  ---  ${stoppedAtStep.toLocaleString()} / ${TOTAL_STEPS.toLocaleString()} steps in ${elapsed} ms ` +
            `(${Math.round(stoppedAtStep / (elapsed / 1000)).toLocaleString()} steps/s), ` +
            `stop latency ${stopLatency} ms, ${chunksRun} chunks -> ` +
            `${progressSeen.length} progress + ${midRunSnapshots} snapshot`);

section("the debugger survives an interrupted run");
send({ type: "step" });
snap = (await waitFor(ofType("snapshot"), { label: "step after stop" })).data;
eq(snap.registers.step, stoppedAtStep + 1, "step() works on the instruction boundary the stop left");
send({ type: "back" });
snap = (await waitFor(ofType("snapshot"), { label: "back after stop" })).data;
eq(snap.registers.step, stoppedAtStep, "step_back() works too");

section("maxSteps -> the 'limit' stop reason");
send({ type: "reset" });
await waitFor(ofType("snapshot"), { label: "reset for limit" });
send({ type: "run", chunk: 1000, maxSteps: 20000 });
stopped = await waitFor(ofType("stopped"), { label: "stopped at limit" });
eq(stopped.reason, "limit", "maxSteps produces reason 'limit'");
ok(stopped.data.registers.step >= 20000 && stopped.data.registers.step < 21000,
   "stopped within one chunk of the limit", `${stopped.data.registers.step} steps`);

section("input");
const cat = await readExample("cat2.mal");
send({ type: "load", source: cat, input: "hi" });
await waitFor(ofType("snapshot"), { label: "load cat2" });
send({ type: "run" });
stopped = await waitFor(ofType("stopped"), { label: "stopped cat2" });
ok(stopped.data.registers.input_total === 2, "input_total reflects the supplied input",
   `${stopped.data.registers.input_total}`);
ok(stopped.data.registers.output_len >= 2, "cat echoed its input",
   `${stopped.data.registers.output_len} chars out`);

section("stop is a no-op when nothing is running");
//
// The reachable version of this race, not a hypothetical one. `stop` skips the
// command queue so it can interrupt a run; `bridge.js` flips its own `running`
// when `run` is posted, while the worker flips its own only when `doRun` starts
// -- after the `load` queued ahead of it. So a UI that correctly guards its
// stop button on `running` can still land a stop here while this side is
// neither running nor loaded: click a program, hit run, hit stop, all inside
// the load. Dispatched back to back below, which is exactly that ordering.
const freshEngineMessages = [];
const freshEngine = createEngine({
  post: (m) => freshEngineMessages.push(m),
  loadPyodide: () => loadPyodide(),
  readVendor: async (name) => new Uint8Array(await readFile(join(VENDOR, name))),
});
await freshEngine.booted;
freshEngine.dispatch({ type: "load", source: bottles, id: "race-load" });
freshEngine.dispatch({ type: "run", chunk: DEFAULT_CHUNK, maxSteps: 5000, id: "race-run" });
freshEngine.dispatch({ type: "stop", id: "race-stop" });
const raceStopped = freshEngineMessages.find((m) => m.type === "stopped" && m.id === "race-stop");
ok(raceStopped !== undefined, "the stop is answered synchronously, ahead of the queue");
eq(raceStopped?.data, null, "with data: null, since nothing is loaded yet");
await waitForEvent(
  () => freshEngineMessages.some((m) => m.type === "stopped" && m.id === "race-run"),
  "the queued run finishing",
);
ok(!freshEngineMessages.some((m) => m.type === "error"), "and no error is produced anywhere",
   JSON.stringify(freshEngineMessages.filter((m) => m.type === "error").map((m) => m.message)));
const raceLoad = freshEngineMessages.find((m) => m.type === "snapshot" && m.id === "race-load");
ok(raceLoad?.data?.registers?.step === 0, "the load it overtook still completes");
const raceRun = freshEngineMessages.find((m) => m.type === "stopped" && m.id === "race-run");
ok(raceRun?.data?.registers?.step === 5000, "and so does the run behind it",
   `${raceRun?.data?.registers?.step} steps`);

section("bad input is an error, not a crash");
send({ type: "load", source: "not malbolge", id: "bad-load" });
await waitFor((m) => m.type === "error" && m.id === "bad-load", { label: "load error" }).catch(() => {});
const loadErr = messages.find((m) => m.type === "error" && m.id === "bad-load");
eq(loadErr?.kind, "load", "invalid source -> error kind 'load'");
send({ type: "banana", id: "bad-type" });
const protoErr = await new Promise((r) => setTimeout(() => r(messages.find((m) => m.type === "error" && m.id === "bad-type")), 50));
eq(protoErr?.kind, "protocol", "unknown message type -> error kind 'protocol'");

// ---------------------------------------------------------------- the bridge
//
// Everything above drives the worker engine directly. This drives bridge.js,
// the API the screens actually use, across a fake Worker that does what a real
// one does: structuredClone in both directions and deliver asynchronously. It
// is the only place the promise/event-bus half of §5.2 gets exercised.

section("bridge.js over a fake Worker");

class FakeWorker {
  constructor() {
    // A real Worker queues outbound messages as tasks on the main thread, so
    // nothing posted during worker startup is lost before the constructor
    // returns and `onmessage` gets assigned. The buffer reproduces that; the
    // engine boots synchronously enough to emit `booting: vendor` before the
    // MalbolgeBridge constructor has finished.
    this._buffer = [];
    this._onmessage = null;
    this.engine = createEngine({
      post: (msg) => this._deliver({ data: structuredClone(msg) }),
      loadPyodide: () => loadPyodide(),
      readVendor: async (name) => new Uint8Array(await readFile(join(VENDOR, name))),
    });
  }
  get onmessage() {
    return this._onmessage;
  }
  set onmessage(fn) {
    this._onmessage = fn;
    const queued = this._buffer;
    this._buffer = [];
    for (const ev of queued) setTimeout(() => fn(ev), 0);
  }
  _deliver(ev) {
    if (this._onmessage) setTimeout(() => this._onmessage(ev), 0);
    else this._buffer.push(ev);
  }
  postMessage(msg) {
    // A real worker delivers on a task, never synchronously.
    setTimeout(() => this.engine.dispatch(structuredClone(msg)), 0);
  }
  terminate() {}
}

const bridge = new MalbolgeBridge({ worker: new FakeWorker() });

const bootPhases = [];
bridge.on("booting", (m) => bootPhases.push(m.phase));
const readyInfo = await bridge.ready;
ok(readyInfo.type === "ready", "bridge.ready resolves with the ready message", `boot ${readyInfo.totalMs} ms`);
ok(bootPhases.length === 4, "booting events reached the bus", bootPhases.join(","));

const loadSnap = await bridge.load(hello, { memCount: 24 });
eq(loadSnap.registers.step, 0, "bridge.load resolves with the snapshot");
ok(bridge.lastSnapshot === loadSnap, "bridge.lastSnapshot tracks it");

const stepSnap = await bridge.step();
eq(stepSnap.registers.step, 1, "bridge.step resolves with the next snapshot");

await bridge.seek(0);
await bridge.step().then(() => bridge.step());
const rejected = await bridge.seek(999_999).then(() => null, (e) => e);
ok(rejected instanceof Error && rejected.kind === "seek", "bridge.seek rejects with kind 'seek'",
   JSON.stringify(rejected?.message));

// run() and stop() are two promises answered by one `stopped` message.
await bridge.load(bottles);
const progressOnBus = [];
bridge.on("progress", (m) => progressOnBus.push(m));
const runP = bridge.run();
ok(bridge.running === true, "bridge.running is true while running");
await new Promise((r) => setTimeout(r, 400));
const stopP = bridge.stop();
const [runStopped, stopStopped] = await Promise.all([runP, stopP]);
eq(runStopped.reason, "stopped", "bridge.run resolves at the stop");
ok(stopStopped === runStopped, "bridge.stop resolves with the same message");
ok(bridge.running === false, "bridge.running cleared");
ok(progressOnBus.length >= 1, "progress reached the bus", `${progressOnBus.length} events`);
ok(runStopped.data.registers.step < TOTAL_STEPS / 10, "and it stopped early here too",
   `${runStopped.data.registers.step.toLocaleString()} steps`);

bridge.terminate();

section("createSession() -- the screen-facing facade");
//
// The locked contract: commands return undefined and every result comes back
// as an event, so a screen has exactly one update path. This section drives it
// the way a screen does -- fire a command, wait for the event.

const bootSeen = [];
const session = await createSession({
  worker: new FakeWorker(),
  onBoot: (phase) => bootSeen.push(phase),
});
ok(bootSeen.join(",") === "vendor,pyodide,wheel,import", "onBoot sees every phase during boot", bootSeen.join(","));
ok(session.ready === true, "session.ready is a boolean, true once booted");

const sessionSnapshots = [];
const unsubscribe = session.on("snapshot", (data, msg) => sessionSnapshots.push({ data, msg }));

const loadReturn = session.load(hello, "abc");   // input positional
ok(loadReturn === undefined, "commands return undefined, not a promise");
await waitForEvent(() => sessionSnapshots.length === 1, "load snapshot event");
ok(sessionSnapshots[0].data?.registers?.step === 0,
   "the handler is given the snapshot itself, not the envelope");
ok(sessionSnapshots[0].msg?.type === "snapshot", "and the raw message as a second argument");
eq(sessionSnapshots[0].data.registers.input_total, 3, "positional input reached the debugger");

session.step();
await waitForEvent(() => sessionSnapshots.length === 2, "step snapshot event");
eq(sessionSnapshots[1].data.registers.step, 1, "step arrives as a snapshot event");

const sessionErrors = [];
session.on("error", ({ message, kind }) => sessionErrors.push({ message, kind }));
session.seek(999);
await waitForEvent(() => sessionErrors.length === 1, "seek error event");
eq(sessionErrors[0].kind, "seek", "error handlers get {message, kind}");
ok(/beyond max_step_reached/.test(sessionErrors[0].message), "with the backend's message",
   JSON.stringify(sessionErrors[0].message));

unsubscribe();
const before = sessionSnapshots.length;
session.step();
await waitForEvent(() => session.lastSnapshot?.registers?.step === 2, "step after unsubscribe");
eq(sessionSnapshots.length, before, "on() returns a working unsubscribe");

// run/stop through the session: results arrive as `progress` and `stopped`.
const sessionProgress = [];
let sessionStopped = null;
session.on("progress", ({ step }) => sessionProgress.push(step));
session.on("stopped", ({ reason, data }) => (sessionStopped = { reason, data }));
session.load(bottles);
await waitForEvent(() => session.lastSnapshot?.registers?.step === 0, "load 99bottles");
session.run({ chunk: DEFAULT_CHUNK });
ok(session.running === true, "session.running while running");
await new Promise((r) => setTimeout(r, 400));
session.stop();
await waitForEvent(() => sessionStopped !== null, "stopped event");
eq(sessionStopped.reason, "stopped", "stopped event carries {reason, data}");
ok(sessionStopped.data.registers.step < TOTAL_STEPS / 10, "and it stopped early here too",
   `${sessionStopped.data.registers.step.toLocaleString()} steps`);
ok(sessionProgress.length >= 1, "progress events carry {step}", `${sessionProgress.length} events`);
ok(session.running === false, "session.running cleared");

ok(session.raw instanceof MalbolgeBridge, "session.raw is the bridge underneath");
session.dispose();
ok(session.ready === false, "session.ready is false after dispose()");

// ------------------------------------------------------------------ summary

console.log(`\n${failures === 0 ? "PASS" : "FAIL"}  ${checks - failures}/${checks} checks in ${((Date.now() - t0) / 1000).toFixed(1)} s`);
process.exit(failures === 0 ? 0 : 1);
