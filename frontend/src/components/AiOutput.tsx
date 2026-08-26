/** What the model produced, rendered properly and takeable away.
 *
 *  Two jobs. It renders Markdown as Markdown rather than as literal text, and
 *  it lets the result leave the screen — because most of what this generates is
 *  written *for* somebody else. A counselling sheet goes to a patient, a
 *  campaign draft goes to whoever signs it off, an account summary goes into a
 *  meeting. Content that can only be read in the tab that made it is content
 *  that gets retyped somewhere else, badly.
 *
 *  Three formats, chosen for what each is actually for:
 *
 *  * **Markdown** — the original, losing nothing. For anyone who will edit it.
 *  * **Word** — an HTML document with Word's own MIME type, which Word opens
 *    and treats as a real document. A genuine .docx would need a library
 *    an order of magnitude larger than everything here, to produce a file that
 *    opens in the same program.
 *  * **PDF** — the browser's own print-to-PDF, in a window styled for paper.
 *    Every machine already has a PDF writer and it renders exactly what the
 *    person just approved on screen, which a re-implementation would not.
 */
import { useState } from "react";
import Markdown, { markdownToHtml } from "./Markdown";
import { useToast } from "./Toast";

interface Props {
  text: string;
  /** Used for the filename and the document heading. */
  title?: string;
  /** Where it came from, printed on the document so a page on a desk has provenance. */
  context?: string;
  className?: string;
}

function download(name: string, body: BlobPart, mime: string) {
  const url = URL.createObjectURL(new Blob([body], { type: mime }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

function safeName(title: string) {
  return (title || "rx5000-note").replace(/[^\w\s-]/g, "").trim().replace(/\s+/g, "-").slice(0, 60);
}

/** Print styling, shared by the Word file and the PDF window. */
function documentHtml(title: string, context: string, bodyHtml: string) {
  const stamp = new Date().toLocaleString();
  return `<!doctype html><html><head><meta charset="utf-8" />
<title>${title}</title>
<style>
  body { font-family: Calibri, Arial, sans-serif; font-size: 11pt; color: #16161d;
         line-height: 1.5; margin: 2cm; }
  h1 { font-size: 18pt; margin: 0 0 4pt; }
  h2 { font-size: 14pt; margin: 16pt 0 4pt; }
  h3 { font-size: 12pt; margin: 12pt 0 4pt; }
  table { border-collapse: collapse; width: 100%; margin: 8pt 0; }
  th, td { border: 1px solid #999; padding: 5pt 7pt; text-align: left; font-size: 10pt; }
  th { background: #eee; }
  code { font-family: Consolas, monospace; background: #f2f2f2; padding: 1pt 3pt; }
  pre { background: #f2f2f2; padding: 8pt; white-space: pre-wrap; }
  blockquote { margin: 8pt 0; padding-left: 10pt; border-left: 3px solid #ccc; color: #444; }
  .meta { color: #666; font-size: 9pt; margin-bottom: 14pt;
          border-bottom: 1px solid #ddd; padding-bottom: 6pt; }
</style></head><body>
<h1>${title}</h1>
<div class="meta">${context ? context + " &middot; " : ""}Generated ${stamp} &middot; RX5000</div>
${bodyHtml}
</body></html>`;
}

export default function AiOutput({ text, title = "AI note", context = "", className = "" }: Props) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  if (!text) return null;

  function asMarkdown() {
    download(`${safeName(title)}.md`, text, "text/markdown;charset=utf-8");
  }

  function asWord() {
    // Word reads HTML happily when it is handed this MIME type, and the result
    // is editable rather than a picture of a document.
    const html = documentHtml(title, context, markdownToHtml(text));
    download(`${safeName(title)}.doc`, html, "application/msword");
  }

  function asPdf() {
    const win = window.open("", "_blank", "width=820,height=1000");
    if (!win) {
      // The common case, and worth saying plainly rather than doing nothing.
      toast.error("Your browser blocked the print window. Allow pop-ups for this site, then try again.");
      return;
    }
    win.document.write(documentHtml(title, context, markdownToHtml(text)));
    win.document.close();
    // Waiting for load matters: printing an empty document is the usual result
    // of calling print() the moment after writing to it.
    win.onload = () => { win.focus(); win.print(); };
    // Some browsers fire load before the handler is attached on a written doc.
    setTimeout(() => { try { win.focus(); win.print(); } catch { /* already printed */ } }, 400);
  }

  return (
    <div className={`ai-out ${className}`}>
      <div className="ai-out-bar">
        <span className="ai-out-label">{title}</span>
        <div className="ai-out-actions">
          <button type="button" className="btn ghost small"
                  onClick={() => {
                    navigator.clipboard?.writeText(text)
                      .then(() => toast.ok("Copied."))
                      .catch(() => toast.error("Could not copy to the clipboard."));
                  }}>
            Copy
          </button>
          <div className="ai-out-menu">
            <button type="button" className="btn ghost small" onClick={() => setOpen((o) => !o)}
                    aria-expanded={open} aria-haspopup="menu">
              Download ▾
            </button>
            {open && (
              <div className="ai-out-list" role="menu" onMouseLeave={() => setOpen(false)}>
                <button type="button" onClick={() => { asPdf(); setOpen(false); }}>PDF</button>
                <button type="button" onClick={() => { asWord(); setOpen(false); }}>Word</button>
                <button type="button" onClick={() => { asMarkdown(); setOpen(false); }}>Markdown</button>
              </div>
            )}
          </div>
        </div>
      </div>
      <Markdown text={text} />
    </div>
  );
}
