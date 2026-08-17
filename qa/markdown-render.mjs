/** What the Markdown renderer must get right, including the security part.
 *
 *  Build it first, then run:
 *
 *      cd frontend
 *      npx esbuild src/components/Markdown.tsx --bundle --format=esm \n *        --outfile=../qa/out/Markdown.js --loader:.tsx=tsx --external:react
 *      node ../qa/markdown-render.mjs
 *
 *  Three of these checks exist because the thing failed:
 *
 *  - `dosageNotCode`: the code-span placeholder was a space-delimited
 *    number, so "Take 2 tablets" became a code span.
 *  - `blockquote`: escaping runs before parsing, so by the time the block
 *    parser saw a quote its ">" was already "&gt;" and never matched.
 *  - `scriptNeutralised` and `javascriptUrlBlocked`: the text comes from a
 *    language model and can contain anything, including markup a patient
 *    put in their own notes.
 */
const sample = [
  "# Interaction check", "",
  "**Do not co-prescribe.** Warfarin and *ibuprofen* together raise bleeding risk.", "",
  "| Drug | Dose | Note |",
  "|------|-----:|:----:|",
  "| Warfarin | 5 mg | monitor INR |",
  "| Ibuprofen | 400 mg | avoid |", "",
  "## Actions",
  "1. Take 2 tablets daily",
  "2. Review in `7 days`", "",
  "- Counsel the patient",
  "- Note in the file", "",
  "> Escalate if INR exceeds 4.", "",
  "<script>window.pwned = true;</script>",
  "[Guidance](javascript:alert(1)) and [real](https://example.com)",
].join("\n");
// Imported, not assumed. This file previously called markdownToHtml with no
// import at all, so it threw ReferenceError before checking anything — a test
// that cannot pass is indistinguishable from one nobody ran. The bundle is built
// by the command in the header; if it is missing, say so rather than fail
// obscurely.
const bundle = new URL("./out/Markdown.js", import.meta.url);
let markdownToHtml;
try {
  ({ markdownToHtml } = await import(bundle.href));
} catch (e) {
  console.error([
    "Build the bundle first:",
    "  cd frontend && npx esbuild src/components/Markdown.tsx --bundle"
    + " --format=esm --outfile=../qa/out/Markdown.js --loader:.tsx=tsx --external:react",
    `(${e.message})`,
  ].join("\n"));
  process.exit(2);
}

const html = markdownToHtml(sample);
const has = (s) => html.includes(s);
console.log(JSON.stringify({
  h1: has("<h1>Interaction check</h1>"),
  h2: has("<h2>Actions</h2>"),
  strong: has("<strong>Do not co-prescribe.</strong>"),
  em: has("<em>ibuprofen</em>"),
  table: (html.match(/<tr>/g) || []).length,
  alignRight: has('style="text-align:right"'),
  alignCenter: has('style="text-align:center"'),
  orderedList: has("<ol>"), bulletList: has("<ul>"),
  blockquote: has("<blockquote>"),
  codeSpan: has("<code>7 days</code>"),
  dosageNotCode: has("Take 2 tablets daily"),
  scriptNeutralised: has("&lt;script&gt;") && !has("<script>"),
  javascriptUrlBlocked: !has('href="javascript'),
  realLinkKept: has('href="https://example.com"'),
}, null, 1));
