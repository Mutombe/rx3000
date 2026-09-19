/** The words the pharmacy actually reads, held to one standard.
 *
 *      node qa/words-on-screen.mjs            # report
 *      node qa/words-on-screen.mjs --labels   # only the capitalisation
 *      node qa/words-on-screen.mjs --dashes   # only the dashes
 *
 *  Two rules, both asked for, both about looking like a product somebody paid
 *  for rather than a spreadsheet somebody exported.
 *
 *  THE DASHES. No em or en dash in anything printed or shown. They come from
 *  writing prose in a code comment and then moving the sentence into a label.
 *  A hyphen inside a word is not a dash and is left alone: "Time-Critical" and
 *  "cash-up" are spelled that way.
 *
 *  THE LABELS. A word that names a thing on screen is capitalised: a chip
 *  reading "waiting" beside one reading "Overdue" reads as two different
 *  systems. This is a REPORT, not a rewrite: a label is short, a sentence is
 *  not, and only a human can say which a given string is. So it flags short
 *  standalone strings that start lowercase and sit where a label sits, and
 *  says where each one is.
 *
 *  What it deliberately does not flag: comments, test fixtures, keys, class
 *  names, URLs, anything with a space after a full stop (a sentence), and
 *  placeholders, which are meant to read as an invitation rather than a title.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\//, "");
const only = process.argv.find((a) => a.startsWith("--"));

/** Where shipped words live. */
const ROOTS = [
  join(ROOT, "frontend", "src"),
  join(ROOT, "backend", "app"),
];
const ALSO = [
  join(ROOT, "frontend", "index.html"),
  join(ROOT, "landing", "index.html"),
];

const SKIP_DIR = new Set(["node_modules", "dist", "__pycache__", "assets"]);
const TEXT = /\.(tsx?|py|html)$/;

function walk(dir) {
  let out = [];
  for (const name of readdirSync(dir)) {
    if (SKIP_DIR.has(name)) continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out = out.concat(walk(full));
    else if (TEXT.test(name)) out.push(full);
  }
  return out;
}

const files = ROOTS.flatMap(walk).concat(ALSO);

// ---------------------------------------------------------------- the dashes
//
// Stripping comments first, because a dash in a comment is fine and flagging
// it would bury the ones that matter under hundreds that do not.
/** Blank a multi-line comment WITHOUT losing its newlines.
 *
 *  Deleting them outright shifts every line number after the comment and welds
 *  the line before it onto the line after. That made the first run of this
 *  useless: 855 findings, nearly all of them prose inside comments, reported
 *  against innocent lines that had no dash in them at all.
 */
const blank = (match) => match.replace(/[^\n]/g, " ");

/** Read a file with its line endings normalised.
 *
 *  This repository is checked out with CRLF. In a JavaScript regex `.` never
 *  matches a carriage return, so `//.*$` cannot reach the end of a CRLF line
 *  and every single-line comment survived the strip. That is the whole reason
 *  the first two runs of this reported 855 findings that were nearly all
 *  comments: not the pattern, the invisible character at the end of the line.
 */
const read = (file) => readFileSync(file, "utf8").replace(/\r\n/g, "\n");

function withoutComments(src, file) {
  if (file.endsWith(".py")) {
    return src
      .replace(/"""[\s\S]*?"""/g, blank)     // docstrings
      .replace(/'''[\s\S]*?'''/g, blank)
      .split("\n").map((l) => l.replace(/(^|\s)#.*$/, "$1")).join("\n");
  }
  if (file.endsWith(".html")) return src.replace(/<!--[\s\S]*?-->/g, blank);
  return src
    .replace(/\/\*[\s\S]*?\*\//g, blank)     // block comments, JSX ones too
    .split("\n").map((l) => l.replace(/(^|[^:])\/\/.*$/, "$1")).join("\n");
}

/** A dash standing alone as "there is nothing here" is not prose.
 *
 *  `{value || "—"}` in a table cell is a typographic convention for an empty
 *  figure, the same job a blank would do less legibly, and it is the reason
 *  most of these exist. A dash INSIDE a sentence is the thing that was asked
 *  about: it is prose punctuation that crept out of a code comment and into a
 *  title, a toast or a printed document.
 *
 *  They are counted separately because only the second kind is a fault, and
 *  burying twenty real ones under four hundred table cells is how a report
 *  gets ignored.
 */
const BARE = /["'`>]\s*[—–]\s*["'`<]/;

const dashes = [];
const placeholders = [];
for (const file of files) {
  const src = withoutComments(read(file), file);
  src.split("\n").forEach((line, i) => {
    if (!/[—–]/.test(line)) return;
    const row = { file: relative(ROOT, file), line: i + 1,
                  text: line.trim().slice(0, 100) };
    (BARE.test(line) ? placeholders : dashes).push(row);
  });
}

// ------------------------------------------------------------- the lowercase
//
// A label is short, has no full stop, and is not obviously a sentence. Only
// those are reported: everything longer is prose, where a lowercase start is
// usually correct.
const LABEL_MAX_WORDS = 4;
const ALLOW = /^(e\.?g\.?|per |of |and |or |to |from |in |on |at |by |with |no |\d)/i;

function looksLikeALabel(s) {
  const t = s.trim();
  if (!t || t.length > 42) return false;
  if (!/^[a-z]/.test(t)) return false;                  // already capitalised
  if (/[.!?]\s/.test(t)) return false;                  // a sentence
  if (t.endsWith(".")) return false;
  // Code, not words. The `>text<` pattern also matches the inside of a
  // TypeScript generic — `Promise<void | Promise>` and `useState<api.get>` are
  // not labels, and 80 of them buried the ones that were.
  if (/[(){}[\]|=<>./\\;]/.test(t)) return false;
  if (/^(https?:|\/|#|[a-z-]+\/[a-z-]+)/.test(t)) return false;  // url or path
  if (/^[a-z_]+$/.test(t) && t.includes("_")) return false;      // a key
  if (/^[a-z]+([A-Z][a-z]*)+$/.test(t)) return false;            // camelCase
  if (t.split(/\s+/).length > LABEL_MAX_WORDS) return false;
  if (ALLOW.test(t)) return false;
  return true;
}

/** Strings in the places a label is actually written. */
const LABEL_SITES = [
  // JSX: label={"..."} title={"..."} placeholder is deliberately excluded
  /\b(?:label|title|heading|name|header|empty|caption|legend)\s*[:=]\s*["'`]([^"'`\n]{2,42})["'`]/g,
  // >text< in JSX, a chip or a cell
  />\s*([a-z][^<>{}\n]{1,40})\s*</g,
];

const labels = [];
for (const file of files) {
  if (!/\.(tsx|py)$/.test(file)) continue;
  const src = withoutComments(read(file), file);
  const lines = src.split("\n");
  for (const site of LABEL_SITES) {
    let m;
    site.lastIndex = 0;
    while ((m = site.exec(src))) {
      const value = m[1];
      if (!looksLikeALabel(value)) continue;
      const line = src.slice(0, m.index).split("\n").length;
      labels.push({ file: relative(ROOT, file), line, text: value.trim(),
                    context: (lines[line - 1] || "").trim().slice(0, 90) });
    }
  }
}

// -------------------------------------------------------------------- report
const show = (title, rows, render) => {
  console.log(`\n${title}  (${rows.length})`);
  if (!rows.length) { console.log("  none"); return; }
  for (const r of rows.slice(0, 80)) console.log("  " + render(r));
  if (rows.length > 80) console.log(`  ... and ${rows.length - 80} more`);
};

if (only !== "--labels") {
  show("DASHES inside words that reach a screen or a printer", dashes,
       (r) => `${r.file}:${r.line}  ${r.text}`);
  console.log(`
(plus ${placeholders.length} bare dashes standing alone for `
              + `"nothing here" in a table cell, which are a convention, not prose)`);
}
if (only !== "--dashes") {
  show("LOWERCASE where a label sits", labels,
       (r) => `${r.file}:${r.line}  "${r.text}"`);
}

console.log();
const bad = (only === "--labels" ? 0 : dashes.length) + (only === "--dashes" ? 0 : labels.length);
console.log(bad ? `${bad} to look at` : "the words on screen are consistent");
process.exit(dashes.length ? 1 : 0);
