/** A diagram, when the shape of something is the answer.
 *
 *  Mermaid is a 2MB library and almost nobody asks for a diagram, so it is not
 *  in the bundle. It is fetched the first time one is actually drawn and then
 *  kept: a till that never asks "how does a claim move" never pays for it.
 *
 *  It is also the only place in RX5000 that renders something a model wrote as
 *  markup rather than as text, so it renders into a container of its own and
 *  falls back to showing the source. A diagram that fails to draw should read
 *  as a diagram that failed to draw, not as a blank space where an answer was.
 */
import { useEffect, useRef, useState } from "react";

/** Loaded once per session, on the first diagram anybody asks for. */
let mermaidReady: Promise<any> | null = null;

function mermaid(dark: boolean): Promise<any> {
  if (!mermaidReady) {
    // A real dependency, lazily imported, so the bundler splits it into its
    // own chunk. Fetched from a CDN it would be a diagram that works in the
    // office and fails in a pharmacy whose line is down, and fails always in
    // the desktop build, which has no internet by design.
    mermaidReady = import("mermaid").then((mod: any) => {
      const m = mod.default ?? mod;
      m.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: dark ? "dark" : "neutral",
        fontFamily: "Inter, system-ui, sans-serif",
      });
      return m;
    });
  }
  return mermaidReady;
}

let seq = 0;

export default function AssistantDiagram({ title, source }: {
  title: string;
  source: string;
}) {
  const box = useRef<HTMLDivElement | null>(null);
  const [failed, setFailed] = useState("");
  const dark = typeof document !== "undefined"
    && (document.documentElement.dataset.theme === "dark"
        || (!document.documentElement.dataset.theme
            && window.matchMedia?.("(prefers-color-scheme: dark)").matches));

  useEffect(() => {
    let live = true;
    if (!source?.trim()) return;
    mermaid(dark)
      .then((m) => m.render(`ax-d${++seq}`, source))
      .then(({ svg }: { svg: string }) => {
        if (live && box.current) box.current.innerHTML = svg;
      })
      .catch((e: any) => {
        if (live) setFailed(String(e?.message || e || "that diagram could not be drawn"));
      });
    return () => { live = false; };
  }, [source, dark]);

  return (
    <figure className="ax-diagram">
      {title && <figcaption className="ax-route-title">{title}</figcaption>}
      <div className="ax-diagram-box" ref={box} role="img" aria-label={title || "Diagram"} />
      {failed && (
        // The source, rather than nothing. Somebody can still read the shape
        // out of it, and it says plainly that the drawing is what broke.
        <details className="ax-diagram-fell">
          <summary>That diagram could not be drawn. Here is what it said.</summary>
          <pre>{source}</pre>
        </details>
      )}
    </figure>
  );
}
