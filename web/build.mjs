#!/usr/bin/env node
// Build step for the web/ debugger: populate web/vendor/.
//
// The web build is "fully static, no server" (docs/design/tui-web-architecture.md
// §5.2), so everything the page needs at runtime has to sit next to index.html.
// Pyodide itself comes from the jsdelivr CDN; the three things we self-host are
//
//   vendor/malbolge-<ver>-py3-none-any.whl   the package, unpacked into Pyodide
//   vendor/manifest.json                     examples/manifest.json, verbatim
//   vendor/examples/*.mal                    the programs the manifest names
//   vendor/build.json                        what this script produced, so
//                                            worker.js can find the wheel by
//                                            name without hardcoding a version
//
// §5.2's directory listing only names the wheel and the manifest. The example
// sources are an addition, not a change of plan: the wheel carries no
// examples/ (it is a `malbolge` package wheel), and launch screen 1d lists
// programs the user is then expected to be able to open. Without the sources
// the manifest is a catalogue of files that are not there.
//
// Usage:
//   node build.mjs              rebuild the wheel if stale, then copy
//   node build.mjs --no-build   copy whatever wheel dist/ already has
//   node build.mjs --clean      wipe vendor/ first

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, copyFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(WEB, "..");
const DIST = join(REPO, "dist");
const EXAMPLES = join(REPO, "examples");
const VENDOR = join(WEB, "vendor");

// Kept in step with web/package.json's pyodide dependency, which is what the
// Node smoke test runs against; pinning one version for both is the only way
// smoke.mjs is evidence about the browser.
const FALLBACK_PYODIDE_VERSION = "314.0.6";

const args = new Set(process.argv.slice(2));
const log = (...a) => console.log(...a);

function fail(msg) {
  console.error(`build.mjs: ${msg}`);
  process.exit(1);
}

/** Newest mtime under a directory tree, for staleness comparison. */
function newestMtime(dir) {
  let newest = 0;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "__pycache__" || entry.name.startsWith(".")) continue;
    const p = join(dir, entry.name);
    const t = entry.isDirectory() ? newestMtime(p) : statSync(p).mtimeMs;
    if (t > newest) newest = t;
  }
  return newest;
}

function findWheel() {
  if (!existsSync(DIST)) return null;
  const wheels = readdirSync(DIST)
    .filter((f) => f.startsWith("malbolge-") && f.endsWith("-py3-none-any.whl"))
    .map((f) => ({ name: f, mtime: statSync(join(DIST, f)).mtimeMs }))
    .sort((a, b) => b.mtime - a.mtime);
  return wheels[0] ?? null;
}

function buildWheel() {
  // The project rule is that every Python operation goes through uv.
  log("build.mjs: uv build --wheel");
  const r = spawnSync("uv", ["build", "--wheel"], { cwd: REPO, stdio: "inherit" });
  if (r.error && r.error.code === "ENOENT") {
    fail("`uv` not found on PATH. Install uv, or run with --no-build after building the wheel yourself.");
  }
  if (r.status !== 0) fail(`uv build failed (exit ${r.status})`);
}

// ---------------------------------------------------------------- provenance

/** Run git, or return null if this is not a repo / git is unavailable. */
function git(...argv) {
  const r = spawnSync("git", argv, { cwd: REPO, encoding: "utf8" });
  if (r.error || r.status !== 0) return null;
  return r.stdout.trimEnd();
}

/**
 * What `uv build` will actually package.
 *
 * `uv build` packages the WORKING TREE, not HEAD -- and this repo routinely has
 * several sessions editing in parallel, so at any given moment malbolge/ may be
 * half-written. Refusing to build would be wrong (rebuilding on demand is the
 * right default for day-to-day work); building silently would be worse, because
 * the question this answers -- "which version is the wheel in vendor/ actually
 * from?" -- only ever gets asked afterwards, when nothing is left to answer it.
 * So: warn loudly, build anyway, and stamp the answer into build.json so the
 * artefact carries its own provenance even when nobody read the warning.
 */
function provenance() {
  const head = git("rev-parse", "--short", "HEAD");
  if (head === null) return null;
  const porcelain = git("status", "--porcelain", "--", "malbolge/") ?? "";
  const dirtyPaths = porcelain
    .split("\n")
    .filter(Boolean)
    .map((line) => line.slice(3));
  return { head, dirty: dirtyPaths.length > 0, dirtyPaths };
}

const prov = provenance();

function warnIfDirty() {
  if (!prov) {
    log("build.mjs: WARNING not a git checkout — the wheel's provenance cannot be recorded");
    return;
  }
  if (!prov.dirty) return;
  const shown = prov.dirtyPaths.slice(0, 10);
  log(`build.mjs: WARNING malbolge/ has ${prov.dirtyPaths.length} uncommitted change(s).`);
  log(`build.mjs: WARNING the wheel packages the WORKING TREE, not HEAD (${prov.head}).`);
  for (const path of shown) log(`build.mjs: WARNING     ${path}`);
  if (prov.dirtyPaths.length > shown.length) {
    log(`build.mjs: WARNING     ... and ${prov.dirtyPaths.length - shown.length} more`);
  }
  log("build.mjs: WARNING recorded in vendor/build.json as git.dirty; use --no-build to skip rebuilding.");
}

// ---------------------------------------------------------------- wheel

let wheel = findWheel();
const srcMtime = newestMtime(join(REPO, "malbolge"));
// Whether the git state below describes the wheel itself, or merely the tree at
// the moment an already-built wheel was copied out of dist/.
let gitDescribes = "copy-time";

if (!args.has("--no-build") && (!wheel || wheel.mtime < srcMtime)) {
  if (wheel) log(`build.mjs: ${wheel.name} is older than malbolge/, rebuilding`);
  warnIfDirty();
  buildWheel();
  wheel = findWheel();
  gitDescribes = "wheel";
}
if (!wheel) fail("no wheel in dist/. Run `uv build` (or drop --no-build).");
if (wheel.mtime < srcMtime) {
  log(`build.mjs: WARNING ${wheel.name} is older than malbolge/ (--no-build was given)`);
}

// ---------------------------------------------------------------- vendor

if (args.has("--clean") && existsSync(VENDOR)) rmSync(VENDOR, { recursive: true });
mkdirSync(join(VENDOR, "examples"), { recursive: true });

// Drop any wheel left over from a previous version, so vendor/ never holds two.
for (const f of readdirSync(VENDOR)) {
  if (f.endsWith(".whl") && f !== wheel.name) {
    rmSync(join(VENDOR, f));
    log(`build.mjs: removed stale ${f}`);
  }
}

copyFileSync(join(DIST, wheel.name), join(VENDOR, wheel.name));
log(`build.mjs: vendor/${wheel.name}  ${statSync(join(VENDOR, wheel.name)).size} bytes`);

const manifestPath = join(EXAMPLES, "manifest.json");
if (!existsSync(manifestPath)) fail("examples/manifest.json is missing");
copyFileSync(manifestPath, join(VENDOR, "manifest.json"));
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
log(`build.mjs: vendor/manifest.json  ${manifest.programs.length} programs`);

// Only the programs the manifest names, and only for the variant the web v1
// supports (§5.2: original Malbolge only). Copying examples/ wholesale would
// also ship the .py compiler inputs, which this build cannot do anything with.
let copied = 0;
for (const prog of manifest.programs) {
  const src = join(EXAMPLES, prog.file);
  if (!existsSync(src)) fail(`manifest names ${prog.file}, which is not in examples/`);
  copyFileSync(src, join(VENDOR, "examples", prog.file));
  copied += 1;
}
log(`build.mjs: vendor/examples/  ${copied} files`);

// ---------------------------------------------------------------- build.json

function pyodideVersion() {
  const p = join(WEB, "node_modules", "pyodide", "package.json");
  if (existsSync(p)) return JSON.parse(readFileSync(p, "utf8")).version;
  return FALLBACK_PYODIDE_VERSION;
}

const version = wheel.name.slice("malbolge-".length, -"-py3-none-any.whl".length);
const buildInfo = {
  schema: 1,
  wheel: wheel.name,
  version,
  pyodideVersion: pyodideVersion(),
  variant: manifest.variant,
  builtAt: new Date().toISOString(),
  // Where the wheel came from. `describes: "wheel"` means this run built it, so
  // head/dirty are exactly what went into it; "copy-time" means an existing
  // dist/ wheel was reused and the git state is only as of the copy.
  git: prov ? { ...prov, describes: gitDescribes } : null,
};
writeFileSync(join(VENDOR, "build.json"), JSON.stringify(buildInfo, null, 2) + "\n");
const stamp = prov ? `${prov.head}${prov.dirty ? "-dirty" : ""}` : "no-git";
log(`build.mjs: vendor/build.json  malbolge ${version} @ ${stamp} / pyodide ${buildInfo.pyodideVersion}`);
