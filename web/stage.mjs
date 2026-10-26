#!/usr/bin/env node
// Stage only the browser debugger's runtime assets for static hosting.
import { copyFileSync, lstatSync, mkdirSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(WEB, "..");

function fail(message) {
  throw new Error(message);
}

// Check each component, including vendor/ and screens/, so a symlink cannot
// cause private files outside web/ to enter the public artifact.
function sourceFile(name) {
  let path = WEB;
  for (const part of name.split("/")) {
    path = join(path, part);
    const info = lstatSync(path);
    if (info.isSymbolicLink()) fail(`symlink input is not allowed: ${name}`);
  }
  if (!lstatSync(path).isFile()) fail(`input is not a regular file: ${name}`);
  return path;
}

function jsonInput(name) {
  return JSON.parse(readFileSync(sourceFile(name), "utf8"));
}

function stage() {
  const args = process.argv.slice(2);
  if (args.length > 1) fail("usage: node web/stage.mjs [output-directory]");
  const output = args.length ? resolve(args[0]) : join(REPO, "_site");

  const build = jsonInput("vendor/build.json");
  const manifest = jsonInput("vendor/manifest.json");
  if (!build || typeof build.wheel !== "string"
      || !/^malbolge-[A-Za-z0-9][A-Za-z0-9._+!]*-py3-none-any\.whl$/.test(build.wheel)) {
    fail("build.json must name a portable malbolge wheel without a path");
  }
  if (!manifest || !Array.isArray(manifest.programs)) {
    fail("manifest.json must contain a programs array");
  }
  const names = [
    "index.html", "bridge.js", "worker.js", "theme.js",
    "screens/launch.js", "screens/debugger.js",
    "vendor/build.json", "vendor/manifest.json", `vendor/${build.wheel}`,
  ];
  for (const program of manifest.programs) {
    if (!program || typeof program.file !== "string"
        || !/^[A-Za-z0-9][A-Za-z0-9._-]*\.mal$/.test(program.file)) {
      fail("manifest programs must name .mal files without paths");
    }
    names.push(`vendor/examples/${program.file}`);
  }

  // Resolve every input before creating or writing the output directory.
  const inputs = [...new Set(names)].map((name) => [name, sourceFile(name)]);
  let info;
  try {
    info = lstatSync(output);
  } catch (err) {
    if (err.code !== "ENOENT") throw err;
  }
  if (info) {
    if (info.isSymbolicLink() || !info.isDirectory() || readdirSync(output).length) {
      fail("output must be a new or empty directory; existing contents were preserved");
    }
  }
  mkdirSync(output, { recursive: true });
  for (const [name, source] of inputs) {
    const destination = join(output, name);
    mkdirSync(dirname(destination), { recursive: true });
    copyFileSync(source, destination);
  }
  console.log(`stage.mjs: ${inputs.length} runtime files staged in ${relative(REPO, output) || "."}`);
}

try {
  stage();
} catch (err) {
  console.error(`stage.mjs: ${err.message}`);
  process.exitCode = 1;
}
