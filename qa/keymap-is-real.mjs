/** The key map must describe keys that exist.
 *
 *      node qa/keymap-is-real.mjs
 *
 *  `frontend/src/keymap.ts` is not just documentation. `tools/build_atlas.py`
 *  reads it into the atlas, and RX-Assistant answers "which key does that?"
 *  out of the atlas. So an entry in that file is not a note to ourselves: it
 *  is the assistant telling a dispenser, with total confidence, to press a
 *  key. A key that does nothing is worse than no answer, because the dispenser
 *  presses it, nothing happens, and they stop trusting the assistant.
 *
 *  It had drifted badly: F2 listed as Ointment when the screen uses it to find
 *  the patient, F3 as marking a line cash when it adds a medicine, plus F7,
 *  F11, Ctrl+R and eight Ctrl navigation keys that no screen had ever bound.
 *
 *  So: every script key in keymap.ts must be bound in the dispensary's own
 *  table, with the same label, and every key the dispensary binds must be
 *  listed. The screen is the authority; the map follows it.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC = join(new URL("..", import.meta.url).pathname.replace(/^\//, ""),
                 "frontend", "src");
const read = (p) => readFileSync(join(SRC, p), "utf8");

/** Entries of one exported list in keymap.ts. */
function mapped(name) {
  const src = read("keymap.ts");
  const body = new RegExp(`export const ${name}[^=]*=\\s*\\[(.*?)\\n\\];`, "s").exec(src);
  if (!body) throw new Error(`${name} is not in keymap.ts`);
  const out = [];
  // Entries span lines, so split on the object boundary rather than newlines.
  for (const chunk of body[1].split(/\},\s*\{/)) {
    const combo = /combo:\s*"([^"]+)"/.exec(chunk);
    const label = /label:\s*"([^"]+)"/.exec(chunk);
    if (combo && label) out.push({ combo: combo[1], label: label[1] });
  }
  return out;
}

/** What the dispensary actually binds. */
function bound() {
  const src = read("pages/Dispense.tsx");
  const table = /const hotkeys: Hotkey\[\] = \[(.*?)\n  \];/s.exec(src);
  if (!table) throw new Error("the hotkeys table is not where this expects it");
  const out = [];
  const re = /\{\s*combo:\s*"([^"]+)",\s*label:\s*"([^"]+)"/g;
  let m;
  while ((m = re.exec(table[1]))) out.push({ combo: m[1], label: m[2] });
  return out;
}

const say = [];
const listed = mapped("SCRIPT_KEYS");
const real = bound();
const byCombo = (rows) => new Map(rows.map((r) => [r.combo, r.label]));
const L = byCombo(listed);
const R = byCombo(real);

for (const [combo, label] of L) {
  if (!R.has(combo)) say.push(`keymap.ts offers ${combo} "${label}", which the dispensary does not bind`);
  else if (R.get(combo) !== label)
    say.push(`${combo}: keymap.ts says "${label}", the dispensary does "${R.get(combo)}"`);
}
// Ctrl+K is bound above the screens, by the assistant dock.
const global = mapped("NAV_KEYS").concat(mapped("RX5000_KEYS"));

// A key the dispensary binds has to be findable somewhere in the map, but it
// may be filed as a global one: `?` opens the key map from any screen and is
// bound on this one like the rest.
const anywhere = byCombo(listed.concat(global));
for (const [combo, label] of R) {
  if (!anywhere.has(combo)) {
    say.push(`the dispensary binds ${combo} "${label}", which keymap.ts does not list`);
  }
}

const dock = read("components/AssistantDock.tsx");
for (const { combo, label } of global) {
  if (combo === "Ctrl+K" && !/ctrlKey \|\| e\.metaKey\) && e\.key\.toLowerCase\(\) === "k"/.test(dock)) {
    say.push(`keymap.ts offers Ctrl+K "${label}", which nothing binds`);
  }
}

if (say.length) {
  console.log("The key map and the screens disagree:\n");
  for (const s of say) console.log("  " + s);
  console.log("\nThe screen is the authority. Correct keymap.ts to match it.");
  process.exit(1);
}
console.log(`ok    every key the map offers is bound   ${listed.length} on the script screen`);
