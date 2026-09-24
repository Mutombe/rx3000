/** Put a document in front of the print dialog, wherever this is running.
 *
 *  A WINDOW IS A POP-UP, AND THE TILL HAS NO WAY TO ALLOW ONE.
 *
 *  Every print path in this application opened a window and wrote the document
 *  into it. In a browser that is right: the reader can scroll it, decide not to
 *  print it, and save it as a PDF from the same dialog, which is what most of
 *  these are for.
 *
 *  The desktop shell is a WebView, and a WebView blocks window.open outright.
 *  There is no pop-up blocker to find and no site to allow, so every one of
 *  those paths either told somebody at a till to "allow pop-ups for this site"
 *  or — worse, in `printDocument` — returned silently and did nothing at all.
 *  A print button that does nothing is the hardest fault in this application
 *  to report, because there is nothing to report.
 *
 *  So: the window where a window works, and a hidden iframe where it does not.
 *  The iframe prints the identical document and needs nobody's permission.
 *
 *  `reader` says which is preferred. A quotation or a claim copy is READ before
 *  it is printed and wants the window. A label or a receipt is not read at all,
 *  and a window on a counter screen is one more thing to close with a queue
 *  waiting, so those go straight to the frame.
 *
 *  CLAIMED NOW, WRITTEN LATER.
 *
 *  `claim` returns a place to print BEFORE the document exists, because a
 *  window has to be opened inside the click that asked for it: one opened after
 *  an await has lost the gesture and a browser treats it as a pop-up. Several
 *  callers here have to resolve a logo or an embedded typeface first, so they
 *  claim the view synchronously and write into it when they have the markup.
 */

/** How long the frame stays in the page after print() is called.
 *
 *  Removing it immediately prints a blank page: the dialog reads the document
 *  after the call returns. The same race the shell's `print_page` waits out
 *  before deleting its temporary file. */
const LINGER = 30_000;

export interface PrintView {
  /** Write the document and open the print dialog on it. */
  write(html: string): void;
  /** Give up without printing, taking any frame back out of the page. */
  cancel(): void;
}

export interface PrintViewOptions {
  /** Prefer a real window, for a document somebody reads before printing. */
  reader?: boolean;
  width?: number;
  height?: number;
}

/** Claim somewhere printable. Call this synchronously, inside the click. */
export function claimPrintView(o: PrintViewOptions = {}): PrintView | null {
  const { reader = false, width = 900, height = 1000 } = o;

  const win = reader
    ? window.open("", "_blank", `width=${width},height=${height}`)
    : null;
  if (win) return { write: (html) => writeAndPrint(win, html), cancel: () => win.close() };

  const frame = document.createElement("iframe");
  frame.setAttribute("aria-hidden", "true");
  // Off-screen rather than display:none. A frame that is not laid out has no
  // page box in some engines and prints blank.
  frame.style.cssText =
    "position:fixed;right:0;bottom:0;width:1px;height:1px;opacity:0;border:0;";
  document.body.appendChild(frame);

  const inner = frame.contentWindow;
  if (!inner) { frame.remove(); return null; }
  return {
    write: (html) => writeAndPrint(inner, html, () => frame.remove()),
    cancel: () => frame.remove(),
  };
}

function writeAndPrint(win: Window, html: string, done?: () => void) {
  win.document.write(html);
  win.document.close();
  // Whichever comes first, and only once: `load` can have fired already by the
  // time this runs, and a document that is never printed because its load
  // event was a moment early is a print button that does nothing.
  let printed = false;
  const go = () => {
    if (printed) return;
    printed = true;
    win.focus();
    win.print();
    if (done) setTimeout(done, LINGER);
  };
  win.onload = () => setTimeout(go, 120);
  setTimeout(go, 600);
}

/** The whole thing at once, for a caller with the markup already in hand. */
export function printView(html: string, o: PrintViewOptions = {}): boolean {
  const view = claimPrintView(o);
  if (!view) return false;
  view.write(html);
  return true;
}
