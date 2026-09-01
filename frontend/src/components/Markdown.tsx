/** Render what the model actually wrote.
 *
 *  Models reply in Markdown, headings, bold, bullet lists, tables, and every
 *  screen here was printing that as literal text inside a `pre-wrap` box. A
 *  pharmacist reading an interaction check saw `## Interactions` and
 *  `**Do not co-prescribe**` rather than a heading and an emphasis, and a table
 *  of doses arrived as a wall of pipe characters. The information was all
 *  there and none of it was legible.
 *
 *  No dependency. What is needed is a defined subset — headings, emphasis,
 *  code, lists, tables, quotes, links, rules, and a parser for that is smaller
 *  than the library that would provide it.
 *
 *  **Everything is escaped before any markup is inserted.** The text arrives
 *  from a language model, which means it can contain anything at all, including
 *  a well-formed `<script>` tag that a patient's own notes put there. Escaping
 *  first and generating tags second is the only ordering that is safe, and it
 *  is why this file never interpolates raw input into HTML.
 */
import { useMemo } from "react";

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Inline marks, applied to already-escaped text. */
function inline(text: string): string {
  let out = text;
  // Code first: nothing inside a code span should be interpreted further.
  const codes: string[] = [];
  out = out.replace(/`([^`]+)`/g, (_m, code) => {
    codes.push(code);
    return `\u0000${codes.length - 1}\u0000`;
  });

  out = out
    .replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/(^|[\s(])_([^_\n]+)_/g, "$1<em>$2</em>")
    .replace(/~~([^~]+)~~/g, "<del>$1</del>");

  // Links. The href is checked rather than trusted: a javascript: URL in a
  // model's reply is exactly the kind of thing that must not become clickable.
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, label, href) => {
    const safe = /^(https?:|mailto:|\/)/i.test(href) ? href : "#";
    return `<a href="${safe}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });

  return out.replace(/\u0000(\d+)\u0000/g, (_m, i) => `<code>${codes[Number(i)]}</code>`);
}

function isTableRule(line: string): boolean {
  return /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(line) && line.includes("-");
}

function cells(line: string): string[] {
  return line.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim());
}

/** Markdown subset to HTML. Input is escaped before anything else happens. */
export function markdownToHtml(source: string): string {
  const lines = escapeHtml(source ?? "").replace(/\r\n/g, "\n").split("\n");
  const html: string[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) { i += 1; continue; }

    // Fenced code
    if (/^\s*```/.test(line)) {
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !/^\s*```/.test(lines[i])) { body.push(lines[i]); i += 1; }
      i += 1;
      html.push(`<pre><code>${body.join("\n")}</code></pre>`);
      continue;
    }

    // Heading
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      const level = heading[1].length;
      html.push(`<h${level}>${inline(heading[2].trim())}</h${level}>`);
      i += 1;
      continue;
    }

    // Horizontal rule
    if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(line)) {
      html.push("<hr />");
      i += 1;
      continue;
    }

    // Table: a header row followed by a rule row.
    if (line.includes("|") && i + 1 < lines.length && isTableRule(lines[i + 1])) {
      const head = cells(line);
      const align = cells(lines[i + 1]).map((c) =>
        c.startsWith(":") && c.endsWith(":") ? "center"
          : c.endsWith(":") ? "right" : "");
      i += 2;
      const body: string[][] = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        body.push(cells(lines[i]));
        i += 1;
      }
      const th = head.map((c, n) =>
        `<th${align[n] ? ` style="text-align:${align[n]}"` : ""}>${inline(c)}</th>`).join("");
      const rows = body.map((r) =>
        `<tr>${r.map((c, n) =>
          `<td${align[n] ? ` style="text-align:${align[n]}"` : ""}>${inline(c)}</td>`).join("")}</tr>`).join("");
      html.push(`<div class="md-table-wrap"><table><thead><tr>${th}</tr></thead><tbody>${rows}</tbody></table></div>`);
      continue;
    }

    // Blockquote. Matched as `&gt;` because escaping runs first — the marker
    // has already been escaped by the time the block parser sees it, which is
    // why testing for a literal ">" here silently never matched.
    if (/^\s*&gt;\s?/.test(line)) {
      const body: string[] = [];
      while (i < lines.length && /^\s*&gt;\s?/.test(lines[i])) {
        body.push(lines[i].replace(/^\s*&gt;\s?/, ""));
        i += 1;
      }
      html.push(`<blockquote>${inline(body.join(" "))}</blockquote>`);
      continue;
    }

    // Lists, ordered or not
    const bullet = /^\s*[-*+]\s+/;
    const numbered = /^\s*\d+[.)]\s+/;
    if (bullet.test(line) || numbered.test(line)) {
      const ordered = numbered.test(line);
      const pattern = ordered ? numbered : bullet;
      const items: string[] = [];
      while (i < lines.length && pattern.test(lines[i])) {
        let item = lines[i].replace(pattern, "");
        i += 1;
        // A wrapped continuation line belongs to the item above it.
        while (i < lines.length && lines[i].trim()
               && !pattern.test(lines[i]) && !/^\s*(#{1,6}\s|&gt;|```)/.test(lines[i])) {
          item += " " + lines[i].trim();
          i += 1;
        }
        items.push(`<li>${inline(item.trim())}</li>`);
      }
      html.push(ordered ? `<ol>${items.join("")}</ol>` : `<ul>${items.join("")}</ul>`);
      continue;
    }

    // Paragraph
    const para: string[] = [];
    while (i < lines.length && lines[i].trim()
           && !/^\s*(#{1,6}\s|&gt;|```|[-*+]\s|\d+[.)]\s)/.test(lines[i])
           && !(lines[i].includes("|") && i + 1 < lines.length && isTableRule(lines[i + 1]))) {
      para.push(lines[i].trim());
      i += 1;
    }
    if (para.length) html.push(`<p>${inline(para.join(" "))}</p>`);
  }

  return html.join("\n");
}

export default function Markdown({ text, className = "" }: { text: string; className?: string }) {
  const html = useMemo(() => markdownToHtml(text), [text]);
  // Safe because markdownToHtml escapes before it generates: every tag in this
  // string was produced by the parser, never carried through from the input.
  return <div className={`md ${className}`} dangerouslySetInnerHTML={{ __html: html }} />;
}
