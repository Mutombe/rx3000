/** Every call to the API must go through the resolved base.
 *
 *      node qa/api-base.mjs
 *
 *  A relative `/api/...` works in development and nowhere else. Vite proxies
 *  /api to the backend on the same origin, so a relative path is invisible
 *  here; in the desktop shell and on the hosted site the frontend and the API
 *  are different origins, and the same line resolves against the app itself
 *  and 404s.
 *
 *  That is not a hypothetical. RX-Assistant shipped with one relative fetch in
 *  it and was dead in the desktop app for days, reporting "this copy of the
 *  server does not have RX-Assistant yet" on a server that had it, which sent
 *  the search to the backend and the deployment and never to the one line
 *  that was wrong. This check is cheap; that week was not.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const SRC = join(new URL("..", import.meta.url).pathname.replace(/^\//, ""),
                 "frontend", "src");

/** `fetch("/api/...")` or fetch(`/api/...`), with no base in front of it. */
const RELATIVE = /\bfetch\(\s*(["'`])\/api\//;

const walk = (dir) => readdirSync(dir).flatMap((name) => {
  const full = join(dir, name);
  if (statSync(full).isDirectory()) return walk(full);
  return /\.tsx?$/.test(name) ? [full] : [];
});

const bad = [];
for (const file of walk(SRC)) {
  readFileSync(file, "utf8").split("\n").forEach((line, i) => {
    if (RELATIVE.test(line)) bad.push(`${relative(SRC, file)}:${i + 1}  ${line.trim()}`);
  });
}

if (bad.length) {
  console.log("These call the API on whatever origin the page happens to be on:\n");
  for (const b of bad) console.log("  " + b);
  console.log("\nPut the resolved base in front of it:  fetch(`${apiBase}/api/...`)");
  process.exit(1);
}
console.log("ok    every API call goes through the resolved base");
