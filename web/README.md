# `web/` — the browser debugger

A fully static Pyodide build of the Malbolge debugger. No server, no bundler,
no build step for the JavaScript: every file here is an ES module the browser
loads directly. The only build step copies the Python wheel and the example
catalogue into `vendor/`.

> **Fresh clone? Run `node web/build.mjs` first.**
>
> `web/vendor/` is a build artefact and is **not** in the repository — it holds
> the Python wheel, the example catalogue and the example sources. Without it
> the page loads and then fails at boot (`vendor/build.json -> 404`). One
> command fixes it, and it needs `uv` on PATH:
>
> ```bash
> node web/build.mjs
> ```

Design: [`docs/design/tui-web-architecture.md`](../docs/design/tui-web-architecture.md)
§5.2 (the worker protocol, normative) and §3 (the snapshot shape).

---

## Layout

```
web/
  index.html      shell
  bridge.js       main thread: worker lifecycle, command API, event bus
  worker.js       Pyodide host — the ONLY place Python is touched
  build.mjs       populates vendor/
  smoke.mjs       Node protocol test, no browser needed
  screens/        launch.js (canvas 1d) · debugger.js (canvas 1a)
  theme.js        the canvas's token sets
  vendor/         generated — see below
```

`vendor/` is produced by `build.mjs` and holds:

| file | source |
|---|---|
| `malbolge-<ver>-py3-none-any.whl` | `dist/`, rebuilt with `uv build --wheel` when stale |
| `manifest.json` | `examples/manifest.json`, verbatim |
| `examples/*.mal` | the programs `manifest.json` names |
| `build.json` | `{wheel, version, pyodideVersion, variant, builtAt}` |

Pyodide itself is **not** vendored — it loads from
`https://cdn.jsdelivr.net/pyodide/v<version>/full/`, with the version read from
`build.json`. Only the wheel and the examples are self-hosted.

The example sources are an addition to §5.2's listing. The wheel is a
`malbolge` *package* wheel and carries no `examples/`, so without them the
launch screen would list programs it cannot open.

---

## Running it locally

```bash
node web/build.mjs                       # populate web/vendor/
uv run python -m http.server 8000 -d web # any static server will do
open http://localhost:8000/
```

`file://` will **not** work: module workers and `fetch` of `vendor/` both need
an origin. No COOP/COEP headers are required — this build uses no
`SharedArrayBuffer` and no threads.

`build.mjs` rebuilds the wheel through `uv build --wheel` whenever anything
under `malbolge/` is newer than the wheel in `dist/`. Flags: `--no-build` to
copy whatever `dist/` already has, `--clean` to wipe `vendor/` first.

## Testing it

```bash
cd web && npm install     # once; pulls the `pyodide` npm package
node build.mjs
node smoke.mjs
```

`smoke.mjs` drives the real worker engine and the real bridge under Node — same
Pyodide, same wheel out of `vendor/`, same protocol — with no browser. It covers
boot, load, step/back, seek (including the `ValueError` past
`max_step_reached`), breakpoints, run-to-breakpoint, run-to-termination,
`maxSteps`, input, and error handling; plus, in one section, that `stop` really
interrupts a long run. It also asserts on every single outbound message that
`structuredClone` succeeds and that a JSON round-trip is the identity — which is
the runtime proof that no `PyProxy` escapes the worker.

What it cannot cover is the browser's own event loop and the real `Worker`
boundary; for those, load the page.

## Deploying

Static hosting, GitHub Pages included: run `node web/build.mjs`, then publish
the `web/` directory (minus `node_modules/`). Nothing is server-rendered and
nothing needs a rewrite rule.

`vendor/` is generated and deliberately **not** tracked, so the deploy workflow
has to run `node web/build.mjs` before publishing. The reasons it stays out of
git: the wheel is a build artefact, so tracking it would mean a 220 KB binary
churn on every Python change; and `vendor/examples/` plus `manifest.json` are
copies of `examples/`, so tracking them would put the same content in the
repository twice and let the two drift. `web/node_modules/` is likewise
ignored.

---

## Architecture

```
index.html / screens/          bridge.js            worker.js          Pyodide
     plain JS objects   ←──  event bus + promises ←── postMessage ←── json.dumps
```

Two invariants shape everything here.

**No `PyProxy` ever leaves the worker.** Pyodide hands `worker.js` exactly one
proxy — `_mw_call`, a Python function — and it takes a JSON string and returns a
JSON string. Everything the main thread receives came out of `json.dumps` in
Python and `JSON.parse` in the worker, so it is plain data by construction
rather than by review. That is the runtime half of the architecture doc's
Rule 2, and it is why the ViewModel layer under `malbolge/view/` may not leak an
`Enum` or a callable.

**`stop` is honoured mid-run.** A Worker has no preemption: `onmessage` only
fires when the event loop is idle. A synchronous
`for (const s of dbg.run_chunked())` would therefore never see a stop message
however finely it chunked the work — `99bottles.mal` is 13.8M steps (~78 s) and
`quine.mal` is 69.5M (~6.5 min), so that is a page frozen for minutes with a
dead stop button. The run loop is `async` and awaits a real macrotask between
chunks so the queued `stop` gets a turn. See `makeYielder()` in `worker.js` for
why it is a `MessageChannel` ping with a `setTimeout` every eighth yield rather
than either alone.

Measured (Node, same wheel, this machine): 170–180k steps/s, boot ~1.15 s,
snapshot 29 KB at `mem_count=288`. A stop sent 1.2 s into `99bottles.mal` lands
at ~245,000 steps — 1.8% of the program — about 30 ms after the message.

### Throttles

Sending a snapshot per chunk would be ~35 Hz × 29 KB ≈ 1 MB/s of `postMessage`;
sending none until `stopped` freezes the panels for the entire run. So during a
run the worker sends:

| | rate | why |
|---|---|---|
| `progress` | 10 Hz (`PROGRESS_INTERVAL_MS`) | a step counter faster than this is unreadable, slower stops looking live; ~60 bytes |
| `snapshot` | 2 Hz (`SNAPSHOT_INTERVAL_MS`) | 58 KB/s and 0.05% of a core — the slowest rate that still reads as "the machine is moving" |

Outside a run, snapshots are sent on every state change: at 0.24 ms each they
are not a bottleneck, so timeline scrubbing may rebuild per drag event.

---

## Worker protocol

Normative table: architecture doc §5.2. What follows is what this
implementation adds to it — the tables themselves are implemented as written.

### Main thread → worker

`load` · `step` · `back` · `run` · `stop` · `seek` · `breakpoint` ·
`watchpoint` · `snapshot` · `reset`, with these additions:

- **`id` (any message, optional).** Echoed on the reply that message produced,
  and absent from anything unsolicited. §5.2 gives no way to tell whose reply
  is whose, which makes a failed `seek` and a successful `step` in flight
  together indistinguishable, and makes a mid-run snapshot look like the answer
  to whatever was last asked. `bridge.js` uses it for exactly that.
- **`run.maxSteps` (optional).** A step budget. It is what makes §5.2's `limit`
  stop reason reachable at all — nothing else in the protocol produces one —
  and gives a page a runaway guard that does not depend on the user finding the
  stop button.
- **`load.variant` (optional, default `"original"`).** Anything else is
  rejected with `kind: "unsupported_variant"`, per §5.2's v1 scope.
- **`load` also accepts `memOffset` / `memCount` / `disasmCount`**, so the
  first snapshot arrives already sized to the panels.
- **`breakpoint.action` / `watchpoint.action`** are `toggle` | `enable` |
  `disable` | `remove`. `toggle` means the gutter click: create it if absent,
  remove it if present. Note it does *not* map onto
  `MalbolgeDebugger.toggle_breakpoint()`, which flips the *enabled* flag —
  `enable`/`disable` are the ones that do.
- **View options are sticky.** `memOffset` / `memCount` / `disasmCount` are
  remembered in the worker, so a panel scrolled once stays scrolled for every
  later automatic snapshot.

### Worker → main thread

`ready` · `booting` · `snapshot` · `progress` · `stopped` · `error`, with:

- `ready` also carries `totalMs`, `version`, `pyodideVersion`.
- `booting.phase` is one of `vendor` → `pyodide` → `wheel` → `import`.
- `progress` also carries `elapsedMs` and `stepsPerSecond`.
- `stopped.reason` is `breakpoint` | `watchpoint` | `terminated` | `stopped` |
  `limit`, plus whatever else `StopReason` produces — see the caveat below.
- `error.kind` is one of `boot`, `load`, `seek`, `protocol`, `no_program`,
  `not_found`, `unsupported_variant`, `python`, `internal`, `worker`,
  `structured_clone`.
- `stopped.data` is `null` in exactly one case: a `stop` arriving before
  anything has been loaded. **Screens must null-check it.**

  This is reachable from a correctly written UI. `stop` is the one command that
  skips the worker's command queue — that is what lets it interrupt a run — and
  the two sides disagree about "running" for a window: `bridge.js` flips its own
  flag when `run` is *posted*, the worker flips its own when the run *starts*,
  which is after whatever is queued ahead of it. So a stop button that correctly
  guards on `running` can still deliver a stop while the worker is neither
  running nor loaded — click a program, hit run, hit stop, all inside the load.
  Answering with a no-op `stopped` rather than a `no_program` error is what keeps
  that harmless; the `load` and the `run` it overtook both complete normally.
  Every other command queues, and those do report `no_program`.

**Caveat on `stopped.reason`.** It is the backend's `StopReason`, and the
backend flattens one case: `MalbolgeDebugger.step()` returns
`input_exhausted` when a program reads past the end of its input, but
`_run_iter` discards that return value and re-reads `get_state()`, which only
knows `running` / `terminated`. So a single `step` reports `input_exhausted`
while a `run` that ends the same way reports `terminated`. That is a
`debugger.py` matter, not a worker one; `examples/manifest.json` records
`input_exhausted` for `cat.mal`, so something else in the tree does distinguish
them.

---

## The main-thread API

`createSession()` is what the screens use. Its shape is fixed by the team
contract; `bridge.js` implements it, it is not this file's to change.

```js
import { createSession } from "./bridge.js";

const session = await createSession({ onBoot: (phase) => showPhase(phase) });

const off = session.on("snapshot", (data) => render(data));   // §3.7, unwrapped
session.on("progress", ({ step }) => tick(step));             // only during run
session.on("stopped",  ({ reason, data }) => finish(reason, data));
session.on("error",    ({ message, kind }) => toast(message));

session.load(source, input);          // input positional
session.step();  session.back();
session.run({ chunk });  session.stop();
session.seek(step);
session.breakpoint(addr, action, conditionText);   // toggle|enable|disable|remove
session.watchpoint(addr, action);
session.snapshot({ memOffset, memCount, disasmCount });
session.reset();

session.ready      // boolean
off();             // on() returns its own unsubscribe
session.dispose(); // terminate the worker
```

Three properties of this are load-bearing rather than stylistic:

- **Commands return `undefined`.** Every state change comes back as a
  `snapshot` event, so a screen has exactly one update path. A command that
  also returned its result would give a screen two, and the two diverge the
  moment a run is pushing throttled snapshots of its own.
- **`on()` returns its unsubscribe function**, so a screen can unbind on exit.
  (`off(type, fn)` exists too, but `on()` wraps the handler, so the bus holds
  the wrapper rather than what you passed — use the returned function.)
- **`createSession()` resolves only once the worker is `ready`, but `onBoot`
  fires throughout.** The launch screen has ~1.15 s of Pyodide boot to narrate
  and must not sit on a blank frame.

Handlers are called with the message's *payload*: `msg.data` for `snapshot`,
and the message itself for `progress` / `stopped` / `error` / `ready`, whose
fields are exactly what the contract above destructures. The raw message is
always the second argument.

### The bridge underneath

`new MalbolgeBridge()` is the protocol-shaped object — reachable as
`session.raw` — whose events are the worker's messages verbatim and whose
commands return promises (`await bridge.step()` resolves with the snapshot;
`run()` and `stop()` resolve with the `stopped` message, and a run interrupted
by a stop resolves both with that one message). It exists because that is the
shape a test wants, and because debugging the boundary is easier when a single
command can be awaited. `smoke.mjs` drives both. **Screens should not use it.**

`bridge.js` also exports `fetchManifest()`, `fetchExample(file)`,
`fetchBuildInfo()` and `vendorURL(path)`, so only one module knows the `vendor/`
layout `build.mjs` produces.

---

## Scope

v1 is **original Malbolge only** (59,049 cells). Malbolge20's 3.48-billion-cell
sparse memory needs its browser-heap behaviour measured before being promised;
`load` rejects it rather than half-supporting it.
