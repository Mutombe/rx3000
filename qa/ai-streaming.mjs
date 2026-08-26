/** Do the AI answers actually arrive a piece at a time?
 *
 *  Not "does the endpoint return 200" — that was true of the blocking version
 *  too. This timestamps each frame: if they all land together it is a slow
 *  request with a spinner on it, not a stream.
 *
 *  Driven with curl rather than a browser on purpose. A real model call takes
 *  fifteen to twenty seconds, and polling a rendered page for that long is a
 *  slow test that proves less: the frames are the thing being checked, and the
 *  page is only the thing that displays them.
 *
 *      node qa/ai-streaming.mjs            (needs the API on 8192)
 */
import { spawn } from "node:child_process";

const API = process.env.API || "http://127.0.0.1:8192";
const login = await fetch(`${API}/api/auth/login`, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ username: "admin", password: "admin123" }),
});
const { access_token } = await login.json();

const PATHS = process.env.PATHS?.split(",") ?? ["/api/ai/counseling/12/stream"];
for (const path of PATHS) {
  const started = Date.now();
  const marks = [];
  let chars = 0;
  const curl = spawn("curl", ["-s", "-N", "-X", "POST", API + path,
    "-H", `Authorization: Bearer ${access_token}`]);
  let buffer = "";
  await new Promise((done) => {
    curl.stdout.on("data", (chunk) => {
      buffer += chunk;
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      for (const f of frames) {
        const line = f.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        const ev = JSON.parse(line.slice(5));
        if (ev.type === "delta") {
          chars += ev.text.length;
          marks.push([(Date.now() - started) / 1000, chars]);
        }
        if (ev.type === "done") { curl.kill(); done(); }
        if (ev.type === "error") { console.log(`  ${path}: ${ev.message}`); curl.kill(); done(); }
      }
    });
    curl.on("close", done);
  });
  const span = marks.length ? marks.at(-1)[0] - marks[0][0] : 0;
  console.log(`${path}\n  ${marks.length} deltas, ${chars} chars, `
    + `first at ${marks[0]?.[0] ?? "-"}s, spread over ${span.toFixed(1)}s `
    + `→ ${span > 0.5 ? "STREAMED" : "ARRIVED AT ONCE"}`);
}
